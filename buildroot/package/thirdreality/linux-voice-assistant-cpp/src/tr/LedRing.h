
#pragma once

namespace lva::tr {

enum class LedState {
    Idle,        // pipeline finished
    Listening,   // wake fired; mic streaming to HA
    Thinking,    // STT done, waiting on intent / TTS
    Speaking,    // TTS playing
    Error,       // pipeline error
    Muted,       // mic muted
    Unmuted,     // mic unmuted
};

void Show(LedState state);

}  // namespace lva::tr
