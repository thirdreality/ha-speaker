%option noyywrap

%{
#include <stdlib.h>

#include "led_helper.h"

#define YY_INPUT(buf,result,max_size)  {\
    result = GetNextChar(buf, max_size); \
    if (  result <= 0  ) \
      result = YY_NULL; \
    }

%}

DIGIT    [0-9]

%%

[ \t]*"#".*\n {
    /* eat up comment lines */
    BeginToken(yytext); 
}

[ \t\r\n]+  {
    /* eat up whitespace */
    BeginToken(yytext); 
}

^{DIGIT}+  {
    BeginToken(yytext); 
    yylval.duration = atoi(yytext);

    return DURATION;
}

[a-fA-F0-9]{3,6} {
    unsigned int color = strtoul(yytext, NULL, 16); 
//	DBG("yytext: %s, original color: 0x%6X\n", yytext, color);
    if (strlen(yytext) == 3) { // RGB vale: A00
        unsigned int red, green, blue;
		blue = color & 0x00F;
		blue = (blue * 0xFF) / 0xF;

		green = (color & 0x0F0) >> 4;
		green = (green * 0xFF) / 0xF;

		red = (color & 0xF00) >> 8;
		red = (red * 0xFF) / 0xF;

		color = (red << 16) + (green << 8) + blue;
//	 	DBG("modified color: 0x%6X\n", color);
   }

    yylval.color = color;

    return COLOR;
}

"loop"    { BeginToken(yytext); return LOOP; }

":" |
"," |
.         {
    BeginToken(yytext);
    return yytext[0];
    }
%%

