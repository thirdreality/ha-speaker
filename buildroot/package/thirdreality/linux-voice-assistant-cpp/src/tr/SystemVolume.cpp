#include "tr/SystemVolume.h"

#include <fcntl.h>
#include <signal.h>
#include <spawn.h>
#include <unistd.h>

#include <algorithm>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>

#include "util/Log.h"

extern char** environ;

namespace lva::tr {

namespace {

constexpr const char* kTag = "trvol";

}  // namespace

void SetSystemVolume(int percent) {
    const int clamped = std::clamp(percent, 0, 100);
    char arg_buf[16];
    std::snprintf(arg_buf, sizeof(arg_buf), "%d%%", clamped);

    char prog[]   = "/usr/bin/pactl";
    char a1[]     = "set-sink-volume";
    char a2[]     = "@DEFAULT_SINK@";
    char* argv[]  = { prog, a1, a2, arg_buf, nullptr };

    posix_spawn_file_actions_t actions;
    posix_spawn_file_actions_init(&actions);
    posix_spawn_file_actions_addopen(&actions, STDIN_FILENO,
                                     "/dev/null", O_RDONLY, 0);
    posix_spawn_file_actions_addopen(&actions, STDOUT_FILENO,
                                     "/dev/null", O_WRONLY, 0);
    posix_spawn_file_actions_addopen(&actions, STDERR_FILENO,
                                     "/dev/null", O_WRONLY, 0);

    pid_t pid = 0;
    const int rc = ::posix_spawn(&pid, prog, &actions, nullptr,
                                 argv, environ);
    posix_spawn_file_actions_destroy(&actions);
    if (rc != 0) {
        LVA_LOGW(kTag, "pactl spawn failed: %s", std::strerror(rc));
        return;
    }
    LVA_LOGI(kTag, "SetVolume %d%% (pid=%d)", clamped, (int)pid);
}

void SetSystemVolumeSilent(int percent) {
    const int clamped = std::clamp(percent, 0, 100);
    char arg_buf[16];
    std::snprintf(arg_buf, sizeof(arg_buf), "%d%%", clamped);

    // pactl set-sink-volume @DEFAULT_SINK@ <N>%
    char prog[]   = "/usr/bin/pactl";
    char a1[]     = "set-sink-volume";
    char a2[]     = "@DEFAULT_SINK@";
    char* argv[]  = { prog, a1, a2, arg_buf, nullptr };

    posix_spawn_file_actions_t actions;
    posix_spawn_file_actions_init(&actions);
    posix_spawn_file_actions_addopen(&actions, STDIN_FILENO,
                                     "/dev/null", O_RDONLY, 0);
    posix_spawn_file_actions_addopen(&actions, STDOUT_FILENO,
                                     "/dev/null", O_WRONLY, 0);
    posix_spawn_file_actions_addopen(&actions, STDERR_FILENO,
                                     "/dev/null", O_WRONLY, 0);

    pid_t pid = 0;
    const int rc = ::posix_spawn(&pid, prog, &actions, nullptr,
                                 argv, environ);
    posix_spawn_file_actions_destroy(&actions);
    if (rc != 0) {
        LVA_LOGW(kTag, "pactl spawn failed: %s", std::strerror(rc));
        return;
    }
    LVA_LOGI(kTag, "SetVolumeSilent %d%% (pid=%d)", clamped, (int)pid);
}

}  // namespace lva::tr
