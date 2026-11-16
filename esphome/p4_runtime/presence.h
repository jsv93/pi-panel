#pragma once
#include <driver/gpio.h>

namespace p4_runtime {
class Presence {
 public:
  void configure(int pin,int debounce){
    debounce_=debounce;
    if(pin==pin_)return;
    if(pin_>=0)gpio_reset_pin(gpio_num_t(pin_));
    pin_=pin;last_=-60000;
    if(pin_>=0){
      gpio_config_t cfg{};cfg.pin_bit_mask=1ULL<<pin_;cfg.mode=GPIO_MODE_INPUT;
      cfg.pull_down_en=GPIO_PULLDOWN_ENABLE;gpio_config(&cfg);
    }
  }
  bool poll(int64_t now){
    if(pin_<0 || !gpio_get_level(gpio_num_t(pin_)) || now-last_<debounce_)return false;
    last_=now;return true;
  }
  int pin()const{return pin_;}
  int level()const{return pin_<0?-1:gpio_get_level(gpio_num_t(pin_));}
  int64_t last_event()const{return last_<0?-1:last_;}
 private:
  int pin_=-1,debounce_=10000;int64_t last_=-60000;
};
}
