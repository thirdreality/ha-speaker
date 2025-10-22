#include <stdlib.h>
#include <errno.h>
#include <unistd.h>

#include <string>
#include <iostream>
#include <fstream>
#include <thread>
#include <mutex>
#include <condition_variable>

#include <gio/gio.h>

#include "led_helper.h"

using namespace std;

static thread led_thread;
static bool led_released = false;
static bool to_idle = false;
mutex led_command_mutex;
condition_variable led_command_cond;
static vector<string> new_animations;

static void write_file(const string &path, unsigned int value)
{
	fstream f;
	f.open(path);
	if (! f.is_open()) {
        // ERROR("failed to open %s", path);
		return;
	}

	char buffer[8];
	f.getline(buffer, sizeof(buffer));
	int old_value = std::stoi(buffer);
	if (value != old_value)
		f << to_string(value);

	f.close();
}

static void show_colors(unsigned int red, unsigned int green, unsigned int blue)
{
	write_file("/sys/class/leds/RGB_R/brightness", red);
	write_file("/sys/class/leds/RGB_G/brightness", green);
	write_file("/sys/class/leds/RGB_B/brightness", blue);
}

static void show_rgb(unsigned int rgb)
{
	rgb = rgb & 0x00FFFFFF;
	unsigned int red = rgb >> 16;;
	unsigned int green = (rgb & 0x00FF00) >> 8;
	unsigned int blue = rgb & 0x0000FF;

	// if (rgb)
		// cout << hex << "before show_colors(). red: " << red << ", green: " << green << ", blue: " << blue << endl;
		// DBG("before show_colors(). red: 0x%X, green: 0x%X, blue:  0x%X\n", red, green , blue);

	show_colors(red, green, blue);
}

static void turn_off_all()
{
	show_rgb(0x000000);
}

void set_new_animations(GVariant *parameters)
{
	gchar *animation;
	GVariantIter *iter;
	gboolean b_to_idle;

	g_variant_get(parameters, "(bas)", &b_to_idle, &iter);
	to_idle = (b_to_idle == TRUE);

	while (g_variant_iter_next(iter, "s", &animation, NULL)) {
		// g_print("animation: %s\n", animation);
		new_animations.push_back(animation);
		g_free(animation);
	}
	g_variant_iter_free(iter);

	lock_guard<mutex> guard(led_command_mutex);

	if (to_idle
		|| !new_animations.empty())
		led_command_cond.notify_one();
}

void led_task()
{
//	PropertyConfigurator::configure("/usr/bin/3r_logging.properties");

	vector<LedShowInfo> led_show_infos;
	int index = 0;
	vector<string> animations;
	while (! led_released) {
		unique_lock<mutex> mlock(led_command_mutex);
		if (led_show_infos.size() == 0) { // wait for new commands when there is no led actions
			// INFO("before led_command_cond.wait()");
			led_command_cond.wait(mlock);
            // INFO("after led_command_cond.wait(). new_animation.size(): %d\n", new_animations.size());
		} else { // try wait when there are other led actions to be done
			chrono::microseconds us(1);
			led_command_cond.wait_for(mlock, us);
		}

		if (! new_animations.empty()) {
			animations = new_animations;
			new_animations.clear();

			// INFO("animation[0]: %d\n", animations[0]);
			led_show_infos = led_animation_parse(animations[0].c_str());
			animations.erase(animations.begin());
			index = 0;
		}

		if (to_idle) {
			led_show_infos.clear();
			index = 0;
			turn_off_all();
			to_idle = false;
			animations.clear();
			mlock.unlock();
			continue;
		}
		mlock.unlock();

		if (index < led_show_infos.size()) {
			if (! led_show_infos[index].loop) {
				//cout << "to_idle: " << to_idle << ", i: " << index << ", duration: " << led_show_infos[index].duration
				//	<< ", color: " << hex << led_show_infos[index].color << ", loop: " << led_show_infos[index].loop << endl;
                // DBG("to_idle: %d, i: %d, , duration: %d, color: 0x%X, loop: %d\n",
                //     to_idle, index, led_show_infos[index].duration, led_show_infos[index].color, led_show_infos[index].loop);
			}
			show_rgb(led_show_infos[index].color);
			::usleep(led_show_infos[index].duration * 1000);

			if (false == led_show_infos[index].loop) {
				// increase the index only if the animation action is not a loop
				index++;
			} else if (! animations.empty()) {
				// there are other animation file to handle
				led_show_infos = led_animation_parse(animations[0].c_str());
				animations.erase(animations.begin());
				index = 0;
			}
		} else {
			// INFO("no more led show infos");
			led_show_infos.clear();
			index = 0;
			animations.clear();
		}
	}
}

extern void extern_event_task_init();
int main(int argc, char **argv) {
	extern_event_task_init();

	led_task();
}
