%{

#include <stdio.h>

#include "led_helper.h"

#define YYERROR_VERBOSE 1
/*
#define YYDEBUG 1
*/
//int yydebug=0;

bool led_loop = false;
%}

%defines

%union {
  unsigned int duration;
  unsigned int color;
}

%token <duration>	DURATION
%token <color>		COLOR

%token LOOP

%start animation

%%

animation
    : statement animation
        { /* DBG("statement animation\n"); */ }
    | statement
        { /* DBG("statement\n"); */ }
    ;
statement
    : DURATION ':' COLOR ',' COLOR ',' COLOR ',' COLOR ',' COLOR ',' COLOR ',' COLOR ',' COLOR ',' COLOR ',' COLOR ',' COLOR ',' COLOR
        {
			unsigned int duration = $1, color = $3;
			/* DBG("DURATION: %d, single COLOR: 0x%x\n", duration, color); */
			led_show_infos.push_back(LedShowInfo(duration, color, led_loop));
		}
    | LOOP
        { /* DBG("loop\n"); */ led_loop = true; }
    ;
%%

void yyerror(char const* s) {
  PrintError((char* )s);
}
