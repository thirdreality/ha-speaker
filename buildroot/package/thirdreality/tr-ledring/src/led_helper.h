#ifndef __LED_HELPER__
#define __LED_HELPER__

#include <vector>

#include "parse.hpp"

using namespace std;

extern bool led_loop;

struct LedShowInfo {
	unsigned int duration;
	unsigned int color;
	bool loop;
	LedShowInfo(unsigned int _duration, unsigned int _color, bool _loop) {
		duration = _duration;
		color = _color;
		loop = _loop;
	}
};

extern vector<LedShowInfo> led_show_infos;

extern int debug;

extern int yylex(void);
extern int yyparse(void);
extern void yyerror(char const*);
extern void yyrestart(FILE *input_file);

extern void DumpRow(void); 
extern int GetNextChar(char *b, int maxBuffer);
extern void BeginToken(char*);
extern void PrintError(char *s, ...);

vector<LedShowInfo> led_animation_parse(const char *infile);

#endif /* __LED_HELPER__ */
