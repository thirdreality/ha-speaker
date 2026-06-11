
#pragma once

#include <atomic>
#include <chrono>
#include <cstdint>
#include <functional>
#include <google/protobuf/message_lite.h>
#include <string>
#include <vector>

namespace lva::audio    { class WakeWordEngine; class PcmRingBuffer; class IAudioPlayer; }
namespace lva::state    { class ServerState; }

namespace lva::satellite {

class Satellite {
   public:
    Satellite(lva::state::ServerState& state,
              lva::audio::PcmRingBuffer& mic_ring,
              lva::audio::WakeWordEngine& engine,
              lva::audio::IAudioPlayer* announce_player);
    ~Satellite();

    Satellite(const Satellite&)            = delete;
    Satellite& operator=(const Satellite&) = delete;

    void OnWakeDetected(const std::string& model_id, float prob);

    // Called when the stop word fires. Stops TTS / timer ring.
    void OnStopDetected();

    bool HandleMessage(std::uint32_t msg_type_id,
                       const ::google::protobuf::MessageLite& msg);

    void OnLoopTick();

    // Called when the last HA connection drops. Resets pipeline state.
    void OnDisconnected();

    // Called when mic is muted. Stops streaming + TTS.
    void OnMuted();

   private:
    // ---- internal helpers (defined in .cpp) ----
    void StartPipeline(const std::string& wake_word_phrase);
    // Begins streaming after the wake-up "ding" sound finishes.
    void OpenStreamToHa(const std::string& wake_word_phrase);
    void StopAudioStreaming();
    void PumpAudioToHa();
    void OnVoiceEvent(int event_type,
                      const std::vector<std::pair<std::string, std::string>>& data);
    void PlayTts();
    void PlayAnnounce(const std::string& media_id,
                      const std::string& preannounce_media_id,
                      bool start_conversation);

    void StartTimerRing();
    void StopTimerRing();
    void OnTimerSoundEof();
    void Duck();
    void Unduck();

    struct PendingWake {
        std::string model_id;
        float       prob = 0.0f;
    };

    lva::state::ServerState&    state_;
    lva::audio::PcmRingBuffer&  mic_ring_;
    lva::audio::WakeWordEngine& engine_;
    lva::audio::IAudioPlayer*   announce_player_ = nullptr;

    std::atomic<bool> pending_wake_{false};
    PendingWake       pending_wake_data_;

    // Pipeline state. Mostly mirrors the Python class's flags.
    bool   is_streaming_audio_ = false;
    bool   pipeline_active_    = false;
    bool   continue_conversation_ = false;
    std::string tts_url_;
    bool   tts_played_         = false;

    bool                                  timer_ringing_ = false;
    std::chrono::steady_clock::time_point timer_ring_start_{};

    // Music player ducking state.
    bool   ducked_           = false;
    double pre_duck_volume_  = 1.0;

    std::atomic<std::int64_t> refractory_until_ns_{0};
};

}  // namespace lva::satellite
