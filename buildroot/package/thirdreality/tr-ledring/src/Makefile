TARGET_LIB     = libtr_ledring.so
TARGET_SERVICE = tr_ledring

LIB_SRCS = thirdreality-ledring.cpp
LIB_OBJS = $(LIB_SRCS:.cpp=.o)

SERVICE_OBJS = led_helper.o lex.o parse.o 3r_ledring_binding.o extern_cmd_handler.o thirdreality-ledring-service.o

LDFLAGS += -L$(TARGET_DIR)/usr/lib \
		   -lgobject-2.0 -lglib-2.0 -lgio-2.0 -lpthread

CXXFLAGS += -fPIC \
			-I$(STAGING_DIR)/usr/include/gstreamer-1.0 \
			-I$(STAGING_DIR)/usr/include/glib-2.0 \
			-I$(STAGING_DIR)/usr/lib/glib-2.0/include/ \
			-I$(STAGING_DIR)/usr/include/gio-unix-2.0/

.PHONY: all install clean

all: $(TARGET_LIB) $(TARGET_SERVICE)

thirdreality-ledring.o: thirdreality-ledring.cpp

$(TARGET_LIB): $(LIB_OBJS)
	$(CXX) $(LDFLAGS) -shared -o $@ $^

$(TARGET_SERVICE): $(SERVICE_OBJS)
	$(CXX) $(LDFLAGS) -o $@ $^

parse.hpp parse.cpp: parse.y
	bison -o parse.cpp $<

lex.cpp: lex.l
	flex -o$(@:%.o=%.d) -i $<

led_helper: parse.cpp lex.cpp parse.hpp $(LED_OBJS)
	@echo $(CXX) $(CXXFLAGS) -oled_helper $(LED_OBJS)
	@$(CXX) $(CXXFLAGS) -oled_helper $(LED_OBJS)
	@echo ' '

led_helper.o: led_helper.cpp parse.hpp led_helper.h
lex.o: lex.cpp parse.hpp led_helper.h
parse.o: parse.cpp parse.hpp led_helper.h
3r_ledring_binding.o: 3r_ledring_binding.cpp
	$(CXX) -c $^ $(CXXFLAGS) -fpermissive -o $@

clean:
	rm -f *.o $(TARGET_LIB) parse.hpp parse.cpp lex.cpp led_helper

install:
	install -m 644 $(TARGET_LIB) $(STAGING_DIR)/usr/lib
	install -D -m 0644 $(TARGET_LIB) $(TARGET_DIR)/usr/share/thirdreality/lib/$(TARGET_LIB)
	install -D -m 0755 $(TARGET_SERVICE) $(TARGET_DIR)/usr/share/thirdreality/bin/$(TARGET_SERVICE)
