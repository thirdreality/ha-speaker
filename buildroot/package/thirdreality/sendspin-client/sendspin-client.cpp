// Sendspin client for ThirdReality speaker — PulseAudio backend
// SPDX-License-Identifier: Apache-2.0
//
// Key design: on_audio_write() BLOCKS (as intended by sendspin-cpp).
// PA stream is opened in on_audio_write() on the sync task thread.
//
// Volume unit conventions (do not mix without converting):
//   * Sendspin protocol on the wire (against MA 2.8.7) : 0-100 percent
//     The sendspin-cpp v0.6.0 docs describe volume as 0-255, but the
//     Music Assistant 2.8.7 sendspin provider rejects connections that
//     publish volume in the 0-255 range right after handshake (verified
//     2026-05-20: switching sync_local_volume from `update_volume(50)` to
//     `update_volume(128)` causes MA to drop the connection immediately).
//     Until MA catches up to the v0.6.0 protocol semantics, we keep the
//     wire format as 0-100 so the field is interoperable with both.
//   * PulseAudio linear : 0.0-1.0 (pa_sw_volume_from_linear)
//   * /data/conf/sound.json : 0-100 percent (voice-assistant reads the same
//     field expecting percent — do not change.)

#include <sendspin/client.h>
#include <sendspin/controller_role.h>
#include <sendspin/metadata_role.h>
#include <sendspin/player_role.h>

#include <pulse/error.h>
#include <pulse/pulseaudio.h>
#include <pulse/simple.h>

#include <atomic>
#include <chrono>
#include <csignal>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <string>
#include <thread>
#include <unistd.h>

using namespace sendspin;

static std::atomic<bool> g_running{true};
static std::atomic<bool> g_ducked{false};
static void signal_handler(int) { g_running = false; }
static void sigusr1_handler(int) { g_ducked = true; }
static void sigusr2_handler(int) { g_ducked = false; }

static constexpr const char *SOUND_CONF = "/data/conf/sound.json";

// Read "volume" (0-100 percent) from sound.json. Returns -1 on failure.
static int read_device_volume() {
  std::ifstream f(SOUND_CONF);
  if (!f) return -1;
  std::string content((std::istreambuf_iterator<char>(f)),
                      std::istreambuf_iterator<char>());
  auto pos = content.find("\"volume\"");
  if (pos == std::string::npos) return -1;
  pos = content.find(':', pos);
  if (pos == std::string::npos) return -1;
  return std::atoi(content.c_str() + pos + 1);
}

// Update "volume" field (0-100 percent) in sound.json with atomic rename.
// Minimal in-place number replace, no jq dependency.
static void persist_volume(int vol) {
  if (vol < 0) vol = 0;
  if (vol > 100) vol = 100;

  std::ifstream in(SOUND_CONF);
  if (!in) return;
  std::string content((std::istreambuf_iterator<char>(in)),
                      std::istreambuf_iterator<char>());
  in.close();

  auto pos = content.find("\"volume\"");
  if (pos == std::string::npos) return;
  pos = content.find(':', pos);
  if (pos == std::string::npos) return;
  pos++;
  while (pos < content.size() && (content[pos] == ' ' || content[pos] == '\t')) pos++;
  auto end = pos;
  while (end < content.size() && (content[end] >= '0' && content[end] <= '9')) end++;
  if (end == pos) return;

  char buf[8];
  snprintf(buf, sizeof(buf), "%d", vol);
  content.replace(pos, end - pos, buf);

  std::string tmp = std::string(SOUND_CONF) + ".tmp";
  std::ofstream out(tmp, std::ios::trunc);
  if (!out) return;
  out << content;
  out.close();
  rename(tmp.c_str(), SOUND_CONF);
}

static int64_t now_us() {
  return std::chrono::duration_cast<std::chrono::microseconds>(
      std::chrono::steady_clock::now().time_since_epoch()).count();
}

// ============================================================================
// Non-blocking volume control via PulseAudio async API
// ============================================================================

class PulseVolumeController {
 public:
  PulseVolumeController() {
    ml_ = pa_threaded_mainloop_new();
    if (!ml_) return;
    ctx_ = pa_context_new(pa_threaded_mainloop_get_api(ml_), "sendspin-vol");
    if (!ctx_) return;
    pa_context_set_state_callback(ctx_, context_state_cb, this);
    pa_context_connect(ctx_, nullptr, PA_CONTEXT_NOFLAGS, nullptr);
    pa_threaded_mainloop_start(ml_);
  }

  ~PulseVolumeController() {
    if (ml_) {
      pa_threaded_mainloop_stop(ml_);
      if (ctx_) {
        pa_context_disconnect(ctx_);
        pa_context_unref(ctx_);
      }
      pa_threaded_mainloop_free(ml_);
    }
  }

  void set_volume_percent(int percent) {
    if (!ctx_ || !ml_) return;
    if (percent < 0) percent = 0;
    if (percent > 100) percent = 100;
    pa_threaded_mainloop_lock(ml_);
    if (pa_context_get_state(ctx_) == PA_CONTEXT_READY) {
      pa_cvolume vol;
      pa_cvolume_set(&vol, 2, pa_sw_volume_from_linear(percent / 100.0));
      auto *op = pa_context_set_sink_volume_by_name(ctx_, "@DEFAULT_SINK@", &vol, nullptr, nullptr);
      if (op) pa_operation_unref(op);
    }
    pa_threaded_mainloop_unlock(ml_);
  }

 private:
  static void context_state_cb(pa_context *c, void *userdata) {
    (void)c;
    (void)userdata;
  }

  pa_threaded_mainloop *ml_{nullptr};
  pa_context *ctx_{nullptr};
};

// ============================================================================
// PulseAudio player listener — blocking on_audio_write
// ============================================================================

class PulsePlayerListener : public PlayerRoleListener {
 public:
  ~PulsePlayerListener() override { close_pa(true); }

  void set_player(PlayerRole *p) { player_ = p; }
  void set_volume_controller(PulseVolumeController *vc) { vol_ctrl_ = vc; }

  // Called on sync task thread. BLOCKS until audio is written.
  size_t on_audio_write(uint8_t *data, size_t length, uint32_t /*timeout_ms*/) override {
    if (length == 0) return 0;

    // Open PA on first call if not yet open
    if (!pa_.load()) {
      // Backoff: avoid hammering pa_simple_new if PA is unavailable
      int64_t now = now_us();
      if (now - last_open_attempt_us_ < backoff_us_) {
        return length;  // Discard until backoff expires
      }
      last_open_attempt_us_ = now;

      pa_sample_spec ss;
      ss.format = PA_SAMPLE_S16LE;
      ss.channels = 2;
      ss.rate = 48000;  // Match PA sink rate to avoid resampling

      if (player_) {
        auto &params = player_->get_current_stream_params();
        if (params.sample_rate.has_value()) ss.rate = params.sample_rate.value();
        if (params.channels.has_value()) ss.channels = static_cast<uint8_t>(params.channels.value());
      }

      // Use small buffer to get tight pacing from pa_simple_write blocking.
      // prebuf=0: start playback immediately (no buffering delay).
      // tlength: target buffer length ~50ms — controls when write blocks.
      uint32_t bytes_per_frame = pa_frame_size(&ss);
      uint32_t tlength_bytes = ss.rate * bytes_per_frame * 50 / 1000;  // 50ms

      pa_buffer_attr ba;
      ba.maxlength = tlength_bytes * 2;
      ba.tlength = tlength_bytes;
      ba.prebuf = 0;
      ba.minreq = (uint32_t)-1;  // Let PA decide minreq
      ba.fragsize = (uint32_t)-1;

      int err = 0;
      auto *pa = pa_simple_new(nullptr, "sendspin-client", PA_STREAM_PLAYBACK, nullptr,
                               "Sendspin", &ss, nullptr, &ba, &err);
      if (pa) {
        frame_size_ = bytes_per_frame;
        current_rate_ = ss.rate;
        current_channels_ = ss.channels;
        pa_.store(pa);
        backoff_us_ = kInitialBackoffUs;  // Reset backoff on success
        fprintf(stderr, "[sendspin] opened PA %uHz %uch (frame=%zu, tlength=%ums)\n",
                ss.rate, ss.channels, frame_size_, tlength_bytes * 1000 / (ss.rate * bytes_per_frame));
      } else {
        fprintf(stderr, "[sendspin] pa_simple_new failed: %s\n", pa_strerror(err));
        // Exponential backoff: 100ms, 200ms, 400ms, ... up to 5s
        backoff_us_ = std::min(backoff_us_ * 2, kMaxBackoffUs);
        return length;  // Discard to keep sync task moving
      }
    }

    auto *pa = pa_.load();

    // Frame-align
    size_t aligned = length - (length % frame_size_);
    if (aligned == 0) return length;

    // Duck: attenuate PCM samples when voice assistant is active
    if (g_ducked.load(std::memory_order_relaxed)) {
      auto *samples = reinterpret_cast<int16_t *>(data);
      size_t count = aligned / sizeof(int16_t);
      for (size_t i = 0; i < count; ++i)
        samples[i] = static_cast<int16_t>(samples[i] >> 2);  // -12dB
    }

    int err = 0;
    if (pa_simple_write(pa, data, aligned, &err) < 0) {
      fprintf(stderr, "pa_simple_write: %s\n", pa_strerror(err));
      // Connection lost (e.g., PA sink reconfigured during voice capture).
      // Close and let next on_audio_write() reopen.
      close_pa(false);
      return length;  // Discard to keep sync task moving
    }

    // Report played frames with future timestamp accounting for PA latency.
    // pa_simple_write just queued data into PA buffer; it will play in the future.
    uint32_t frames = static_cast<uint32_t>(aligned / frame_size_);
    int64_t latency_us = pa_simple_get_latency(pa, nullptr);
    if (latency_us < 0) latency_us = 0;
    int64_t finish_ts = now_us() + latency_us;
    player_->notify_audio_played(frames, finish_ts);

    return aligned;  // Return actual bytes written for proper sync
  }

  // Called on main loop thread when stream starts.
  // If PA is already open with the same rate/channels, just flush buffered
  // audio (cheap). Otherwise close so on_audio_write() reopens with the new
  // format. Closing+reopening costs ~tens of ms (pa_simple_new handshake),
  // so avoiding it on same-format streams matters for snappy seek/skip.
  void on_stream_start() override {
    fprintf(stderr, "[sendspin] on_stream_start\n");

    uint32_t new_rate = 0;
    uint8_t new_channels = 0;
    if (player_) {
      auto &p = player_->get_current_stream_params();
      if (p.sample_rate.has_value()) new_rate = *p.sample_rate;
      if (p.channels.has_value()) new_channels = static_cast<uint8_t>(*p.channels);
    }

    auto *pa = pa_.load();
    if (pa && new_rate != 0 && new_channels != 0 &&
        new_rate == current_rate_ && new_channels == current_channels_) {
      // Same format — flush in place.
      pa_simple_flush(pa, nullptr);
      fprintf(stderr, "[sendspin] flushed PA (same format %uHz %uch)\n",
              new_rate, new_channels);
    } else {
      // Format unknown or changed — close so on_audio_write reopens.
      close_pa(false);
    }
  }

  void on_stream_end() override {
    fprintf(stderr, "[sendspin] on_stream_end\n");
    close_pa(false);  // Flush — don't block, new stream may already be arriving
  }

  // Note: on_stream_clear() existed in sendspin-cpp v0.4.0 but was removed in
  // v0.5.0 (PR #54 "Handle stream/clear internally"). v0.6.0 documents that
  // stream/clear is "a seek within the active stream" with NO listener
  // callback (see player_role.cpp::handle_stream_clear) — the library only
  // flushes its own ring buffer. In practice a seek is almost always followed
  // by a fresh stream/start, and our on_stream_start() above flushes PA in
  // place when the format matches, which covers the audible boundary. A pure
  // stream/clear with no following stream/start would leak up to ~tlength
  // (50ms) of buffered PCM from PA, which is below the perceptual threshold
  // for a seek transition.

  // Server-pushed volume change. Wire format is 0-100 percent against MA 2.8.7
  // (see file header). The library types this as uint8_t but treats it as
  // opaque — we interpret it as percent.
  void on_volume_changed(uint8_t volume_percent) override {
    int percent = volume_percent;
    if (percent > 100) percent = 100;
    last_volume_ = percent;
    if (vol_ctrl_) vol_ctrl_->set_volume_percent(percent);
    persist_volume(percent);
    fprintf(stderr, "[sendspin] volume: %d%%\n", percent);
  }

  void on_mute_changed(bool muted) override {
    fprintf(stderr, "[sendspin] mute: %s\n", muted ? "on" : "off");
  }

  // Called when the server changes the static delay. Logged for now;
  // adoption-plan B will wire this to /data/conf/sound.json persistence.
  void on_static_delay_changed(uint16_t delay_ms) override {
    fprintf(stderr, "[sendspin] static_delay: %u ms\n", delay_ms);
  }

  // Check if local volume changed (e.g., hardware buttons / voice-assistant
  // wrote a new value to sound.json) and sync to server. Wire format is
  // 0-100 percent — sending the raw percent value is what MA 2.8.7 expects.
  void sync_local_volume(PlayerRole &player) {
    int percent = read_device_volume();
    if (percent < 0) return;
    if (percent != last_volume_) {
      player.update_volume(static_cast<uint8_t>(percent));
      last_volume_ = percent;
      fprintf(stderr, "[sendspin] local volume synced: %d%%\n", percent);
    }
  }

 private:
  static constexpr int64_t kInitialBackoffUs = 100'000;   // 100ms
  static constexpr int64_t kMaxBackoffUs = 5'000'000;     // 5s

  void close_pa(bool drain = true) {
    auto *pa = pa_.exchange(nullptr);
    if (pa) {
      if (drain)
        pa_simple_drain(pa, nullptr);
      else
        pa_simple_flush(pa, nullptr);
      pa_simple_free(pa);
      fprintf(stderr, "[sendspin] closed PulseAudio (%s)\n", drain ? "drain" : "flush");
    }
    current_rate_ = 0;
    current_channels_ = 0;
  }

  std::atomic<pa_simple *> pa_{nullptr};
  PlayerRole *player_{nullptr};
  PulseVolumeController *vol_ctrl_{nullptr};
  size_t frame_size_{4};
  uint32_t current_rate_{0};
  uint8_t current_channels_{0};
  int last_volume_{-1};
  int64_t last_open_attempt_us_{0};
  int64_t backoff_us_{kInitialBackoffUs};
};

// ============================================================================

class SimpleMetadataListener : public MetadataRoleListener {
 public:
  void on_metadata(const ServerMetadataStateObject &m) override {
    if (m.artist && m.title)
      fprintf(stderr, "[sendspin] now playing: %s - %s\n",
              m.artist->c_str(), m.title->c_str());
  }

  // v0.5.0+ — server disconnect drops cached metadata. Log so we can spot
  // dangling state in field reports; no UI to clear in this build.
  void on_metadata_clear() override {
    fprintf(stderr, "[sendspin] metadata cleared (server disconnect)\n");
  }
};

class MainClientListener : public SendspinClientListener {
 public:
  void on_time_sync_updated(float error) override {
    fprintf(stderr, "[sendspin] time sync: error=%.1f us\n", error);
  }

  // v0.5.0+ — library asks for low-latency networking. We currently keep
  // BCM43438 power-save permanently disabled at the driver level, so these
  // callbacks are observability-only. Adopting dynamic PM toggling is
  // tracked as adoption-plan C in doc/sendspin_cpp_upgrade_v060.md.
  void on_request_high_performance() override {
    fprintf(stderr, "[sendspin] high-performance requested\n");
  }
  void on_release_high_performance() override {
    fprintf(stderr, "[sendspin] high-performance released\n");
  }
};

// Reports network readiness to the library. The library only consults this
// while the WebSocket server has NOT yet started — once started, this is
// never called again, so it cannot affect post-handshake behavior. We start
// sendspin-client only after ntpdate.sh signals "network up" (S99ha-speaker
// gates startup), so by the time we reach SendspinClient::loop() the
// network is already usable. Returning a constant true here is therefore
// safe and avoids the cost of a syscall per loop iteration.
class HostNetworkProvider : public SendspinNetworkProvider {
 public:
  bool is_network_ready() override { return true; }
};

// ============================================================================

int main(int argc, char *argv[]) {
  std::string connect_url;
  std::string friendly_name = "3RSPK Speaker";
  auto log_level = LogLevel::INFO;

  int opt;
  while ((opt = getopt(argc, argv, "u:vqh")) != -1) {
    switch (opt) {
      case 'u': connect_url = optarg; break;
      case 'v': log_level = LogLevel::DEBUG; break;
      case 'q': log_level = LogLevel::ERROR; break;
      default: return 1;
    }
  }
  if (optind < argc) friendly_name = argv[optind];

  signal(SIGINT, signal_handler);
  signal(SIGTERM, signal_handler);
  signal(SIGUSR1, sigusr1_handler);
  signal(SIGUSR2, sigusr2_handler);

  SendspinClient::set_log_level(log_level);

  SendspinClientConfig config;
  config.client_id = friendly_name;
  config.name = friendly_name;
  config.product_name = "Voice & Music Assistant";
  config.manufacturer = "ThirdReality";
  config.software_version = "1.0.0";

  SendspinClient client(std::move(config));

  PulseVolumeController vol_ctrl;

  PulsePlayerListener player_listener;
  PlayerRoleConfig player_config;
  player_config.audio_formats = {
      {SendspinCodecFormat::FLAC, 2, 44100, 16},
      {SendspinCodecFormat::FLAC, 2, 48000, 16},
      {SendspinCodecFormat::OPUS, 2, 48000, 16},
      {SendspinCodecFormat::PCM, 2, 44100, 16},
      {SendspinCodecFormat::PCM, 2, 48000, 16},
  };
  auto &player = client.add_player(std::move(player_config));
  // NOTE: set_static_delay_adjustable(true) advertises SET_STATIC_DELAY in
  // client/state's supported_commands. We leave this disabled until
  // adoption-plan B (static delay persistence) is implemented and verified
  // against a known-good MA version. See doc/sendspin_cpp_upgrade_v060.md.
  // player.set_static_delay_adjustable(true);
  player_listener.set_player(&player);
  player_listener.set_volume_controller(&vol_ctrl);
  player.set_listener(&player_listener);

  SimpleMetadataListener metadata_listener;
  auto &metadata = client.add_metadata();
  metadata.set_listener(&metadata_listener);
  client.add_controller();

  HostNetworkProvider network;
  MainClientListener client_listener;
  client.set_network_provider(&network);
  client.set_listener(&client_listener);

  client.start_server();
  fprintf(stderr, "[sendspin] listening as \"%s\"\n", friendly_name.c_str());
  if (!connect_url.empty()) client.connect_to(connect_url);

  int poll_count = 0;
  while (g_running) {
    client.loop();

    // Check local volume every ~1s (100 * 10ms)
    if (++poll_count >= 100) {
      poll_count = 0;
      player_listener.sync_local_volume(player);
    }

    std::this_thread::sleep_for(std::chrono::milliseconds(10));
  }

  fprintf(stderr, "[sendspin] shutting down\n");
  client.disconnect(SendspinGoodbyeReason::SHUTDOWN);
  return 0;
}
