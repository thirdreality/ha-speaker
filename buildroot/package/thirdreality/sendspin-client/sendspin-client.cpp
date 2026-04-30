// Sendspin client for ThirdReality speaker — PulseAudio backend
// SPDX-License-Identifier: Apache-2.0
//
// Key design: on_audio_write() BLOCKS (as intended by sendspin-cpp).
// PA stream is opened in on_stream_start() on the main loop thread.

#include <sendspin/client.h>
#include <sendspin/controller_role.h>
#include <sendspin/metadata_role.h>
#include <sendspin/player_role.h>

#include <pulse/error.h>
#include <pulse/simple.h>

#include <atomic>
#include <chrono>
#include <csignal>
#include <cstdio>
#include <string>
#include <thread>
#include <unistd.h>

using namespace sendspin;

static std::atomic<bool> g_running{true};
static void signal_handler(int) { g_running = false; }

static int64_t now_us() {
  return std::chrono::duration_cast<std::chrono::microseconds>(
      std::chrono::steady_clock::now().time_since_epoch()).count();
}

// ============================================================================
// PulseAudio player listener — blocking on_audio_write
// ============================================================================

class PulsePlayerListener : public PlayerRoleListener {
 public:
  ~PulsePlayerListener() override { close_pa(true); }

  void set_player(PlayerRole *p) { player_ = p; }

  // Called on sync task thread. BLOCKS until audio is written.
  size_t on_audio_write(uint8_t *data, size_t length, uint32_t /*timeout_ms*/) override {
    if (length == 0) return 0;

    // Open PA on first call if not yet open
    if (!pa_.load()) {
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
        pa_.store(pa);
        fprintf(stderr, "[sendspin] opened PA %uHz %uch (frame=%zu, tlength=%ums)\n",
                ss.rate, ss.channels, frame_size_, tlength_bytes * 1000 / (ss.rate * bytes_per_frame));
      } else {
        fprintf(stderr, "[sendspin] pa_simple_new failed: %s\n", pa_strerror(err));
        return length;  // Discard to keep sync task moving
      }
    }

    auto *pa = pa_.load();

    // Frame-align
    size_t aligned = length - (length % frame_size_);
    if (aligned == 0) return length;

    int err = 0;
    if (pa_simple_write(pa, data, aligned, &err) < 0) {
      fprintf(stderr, "pa_simple_write: %s\n", pa_strerror(err));
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

  // Called on main loop thread when stream starts
  void on_stream_start() override {
    fprintf(stderr, "[sendspin] on_stream_start\n");
    close_pa(false);  // Flush — discard old audio immediately for fast seek response
  }

  void on_stream_end() override {
    fprintf(stderr, "[sendspin] on_stream_end\n");
    close_pa(false);  // Flush — don't block, new stream may already be arriving
  }

  void on_stream_clear() override {
    fprintf(stderr, "[sendspin] on_stream_clear\n");
    close_pa(false);  // Flush — discard immediately
  }

  void on_volume_changed(uint8_t /*volume*/) override {
    // Volume controlled locally via hardware buttons and /data/conf/sound.json
  }

  void on_mute_changed(bool muted) override {
    fprintf(stderr, "[sendspin] mute: %s\n", muted ? "on" : "off");
  }

  // Called from main loop to handle deferred open
  void try_deferred_open() {}

 private:
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
  }

  std::atomic<pa_simple *> pa_{nullptr};
  PlayerRole *player_{nullptr};
  size_t frame_size_{4};
};

// ============================================================================

class SimpleMetadataListener : public MetadataRoleListener {
 public:
  void on_metadata(const ServerMetadataStateObject &m) override {
    if (m.artist && m.title)
      fprintf(stderr, "[sendspin] now playing: %s - %s\n",
              m.artist->c_str(), m.title->c_str());
  }
};

class DebugClientListener : public SendspinClientListener {
 public:
  void on_time_sync_updated(float error) override {
    fprintf(stderr, "[sendspin] time sync: error=%.1f us\n", error);
  }
};

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

  SendspinClient::set_log_level(log_level);

  SendspinClientConfig config;
  config.client_id = "3rspk-sendspin";
  config.name = friendly_name;
  config.product_name = "Voice & Music Assistant";
  config.manufacturer = "ThirdReality";
  config.software_version = "1.0.0";

  SendspinClient client(std::move(config));

  PulsePlayerListener player_listener;
  PlayerRoleConfig player_config;
  player_config.audio_formats = {
      {SendspinCodecFormat::FLAC, 2, 44100, 16},
      {SendspinCodecFormat::FLAC, 2, 48000, 16},
      {SendspinCodecFormat::PCM, 2, 44100, 16},
      {SendspinCodecFormat::PCM, 2, 48000, 16},
  };
  auto &player = client.add_player(std::move(player_config));
  player_listener.set_player(&player);
  player.set_listener(&player_listener);

  SimpleMetadataListener metadata_listener;
  auto &metadata = client.add_metadata();
  metadata.set_listener(&metadata_listener);
  client.add_controller();

  HostNetworkProvider network;
  DebugClientListener client_listener;
  client.set_network_provider(&network);
  client.set_listener(&client_listener);

  client.start_server();
  fprintf(stderr, "[sendspin] listening as \"%s\"\n", friendly_name.c_str());
  if (!connect_url.empty()) client.connect_to(connect_url);

  while (g_running) {
    client.loop();
    player_listener.try_deferred_open();
    std::this_thread::sleep_for(std::chrono::milliseconds(10));
  }

  fprintf(stderr, "[sendspin] shutting down\n");
  client.disconnect(SendspinGoodbyeReason::SHUTDOWN);
  return 0;
}
