#pragma once
#include "driver/sdmmc_host.h"
#include "sdmmc_cmd.h"
#include "sd_pwr_ctrl_by_on_chip_ldo.h"
#include "esp_vfs_fat.h"
#include "mbedtls/sha256.h"
#include "esp_heap_caps.h"
#include "esp_task_wdt.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include <algorithm>
#include <cstdio>
#include <cstring>
#include <string>
#include <sys/stat.h>

namespace study {
class CardArt {
  inline static sdmmc_card_t *card_=nullptr;
  inline static sd_pwr_ctrl_handle_t power_=nullptr;
  FILE *file_=nullptr;
  size_t length_=0;
  uint8_t verified_[32]{};
  std::string path_;
 public:
  CardArt()=default;
  CardArt(const CardArt&)=delete;
  CardArt &operator=(const CardArt&)=delete;
  ~CardArt(){close();}
  bool mount(){
    if(card_)return true;
    sd_pwr_ctrl_ldo_config_t ldo{};ldo.ldo_chan_id=4;
    const auto powered=sd_pwr_ctrl_new_on_chip_ldo(&ldo,&power_);
    if(powered!=ESP_OK){ESP_LOGW("study_card","SD power setup failed: %s",esp_err_to_name(powered));return false;}
    sdmmc_host_t host=SDMMC_HOST_DEFAULT();
    host.slot=SDMMC_HOST_SLOT_0;host.max_freq_khz=SDMMC_FREQ_DEFAULT;
    host.pwr_ctrl_handle=power_;
    sdmmc_slot_config_t slot=SDMMC_SLOT_CONFIG_DEFAULT();
    slot.width=4;slot.clk=GPIO_NUM_43;slot.cmd=GPIO_NUM_44;
    slot.d0=GPIO_NUM_39;slot.d1=GPIO_NUM_40;slot.d2=GPIO_NUM_41;slot.d3=GPIO_NUM_42;
    slot.flags|=SDMMC_SLOT_FLAG_INTERNAL_PULLUP;
    esp_vfs_fat_mount_config_t options{};
    options.format_if_mount_failed=false;options.max_files=12;
    auto result=esp_vfs_fat_sdmmc_mount("/sd",&host,&slot,&options,&card_);
    if(result==ESP_OK)return true;
    card_=nullptr;sd_pwr_ctrl_del_on_chip_ldo(power_);power_=nullptr;
    ESP_LOGW("study_card","Card mount failed: %s",esp_err_to_name(result));
    return false;
  }
  bool space(uint64_t &total,uint64_t &free)const{
    return card_ && esp_vfs_fat_info("/sd",&total,&free)==ESP_OK;
  }
  void close(){
    if(file_)fclose(file_);
    file_=nullptr;length_=0;path_.clear();
  }
  bool open(const char *path,size_t expected,const uint8_t *digest){
    // Callers reuse the same open, already-verified immutable bank.
    if(file_ && path_==path && length_==expected && !memcmp(verified_,digest,32))return true;
    close();
    if(!card_)return false;
    auto *f=fopen(path,"rb");
    if(!f)return false;
    bool ok=fseek(f,0,SEEK_END)==0 && ftell(f)==long(expected) && fseek(f,0,SEEK_SET)==0;
    if(!ok)ESP_LOGW("study_card","Artwork file length check failed, expected %u",unsigned(expected));
    mbedtls_sha256_context ctx;mbedtls_sha256_init(&ctx);
    ok=ok && mbedtls_sha256_starts(&ctx,0)==0;
    // The SD controller and the SHA accelerator both use DMA. Keep their
    // shared buffer in internal DMA-capable memory, aligned to a cache line.
    constexpr size_t block_size=8192;
    auto *block=static_cast<uint8_t*>(heap_caps_aligned_alloc(128,block_size,MALLOC_CAP_INTERNAL|MALLOC_CAP_DMA|MALLOC_CAP_8BIT));
    ok=ok && block;
    for(size_t n=0;ok && n<expected;){
      size_t take=std::min(block_size,expected-n);
      size_t got=fread(block,1,take,f);
      const int result=got==take?mbedtls_sha256_update(&ctx,block,take):-1;
      ok=got==take && result==0;
      if(!ok)ESP_LOGW("study_card","Artwork read at %u requested %u received %u SHA status %d",unsigned(n),unsigned(take),unsigned(got),result);
      n+=take;
      if(n%(128*1024)==0){
        if(esp_task_wdt_status(nullptr)==ESP_OK)esp_task_wdt_reset();
        vTaskDelay(1);
      }
    }
    heap_caps_free(block);
    uint8_t actual[32]{};
    if(ok){
      ok=mbedtls_sha256_finish(&ctx,actual)==0 && !memcmp(digest,actual,32);
      if(!ok)ESP_LOGW("study_card","Artwork hash prefix %02x%02x%02x%02x expected %02x%02x%02x%02x",actual[0],actual[1],actual[2],actual[3],digest[0],digest[1],digest[2],digest[3]);
    }
    mbedtls_sha256_free(&ctx);
    if(!ok){ESP_LOGW("study_card","Artwork verification failed");fclose(f);return false;}
    file_=f;length_=expected;path_=path;memcpy(verified_,digest,32);return true;
  }
  bool read(size_t offset,void *dest,size_t bytes){
    return file_ && offset<=length_ && bytes<=length_-offset &&
      fseek(file_,long(offset),SEEK_SET)==0 && fread(dest,1,bytes,file_)==bytes;
  }
};
}
