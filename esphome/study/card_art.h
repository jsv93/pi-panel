#pragma once
#include "driver/sdmmc_host.h"
#include "sdmmc_cmd.h"
#include "sd_pwr_ctrl_by_on_chip_ldo.h"
#include "esp_vfs_fat.h"
#include "diskio_sdmmc.h"
#include "mbedtls/sha256.h"
#include "esp_heap_caps.h"
#include "esp_task_wdt.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include <algorithm>
#include <cstdio>
#include <cstring>
#include <string>
#include <sys/stat.h>
#include <fcntl.h>
#include <unistd.h>
#include <mutex>

namespace study {
class CardArt {
  inline static sdmmc_card_t *card_=nullptr;
  inline static sd_pwr_ctrl_handle_t power_=nullptr;
  inline static std::mutex mount_mutex_;
  inline static int64_t retry_mount_at_=0;
  int file_=-1;
  uint8_t *read_buffer_=nullptr;
  static constexpr size_t read_block_size=8192;
  size_t length_=0;
  uint8_t verified_[32]{};
  std::string path_;
  struct Extent {size_t first,bytes,sector;};
  Extent *extents_=nullptr;
  size_t extent_count_=0;
  int volume_=-1;
#if FF_FS_REENTRANT
  struct VolumeLock {
    int volume;
    bool acquired;
    explicit VolumeLock(int value):volume(value),acquired(value>=0 && ff_mutex_take(value)){}
    ~VolumeLock(){if(acquired)ff_mutex_give(volume);}
  };
#endif
  // Immutable, SHA-named banks can use FatFs's verified cluster map. Reading
  // adjacent sectors together avoids one SD command per 512-byte cluster.
  void map_extents(const char *path,size_t expected){
#if FF_USE_FASTSEEK && FF_FS_REENTRANT
    if(strncmp(path,"/sd/",4) || card_->csd.sector_size!=512)return;
    const auto drive=ff_diskio_get_pdrv_card(card_);
    if(drive>=FF_VOLUMES)return;
    const std::string native=std::to_string(drive)+":"+(path+3);
    FIL file{};
    if(f_open(&file,native.c_str(),FA_READ)!=FR_OK)return;
    DWORD *map=nullptr;
    DWORD capacity=64;
    FRESULT result=FR_NOT_ENOUGH_CORE;
    while(result==FR_NOT_ENOUGH_CORE && capacity<=4096){
      auto *next=static_cast<DWORD*>(heap_caps_realloc(map,capacity*sizeof(DWORD),MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT));
      if(!next)break;
      map=next;map[0]=capacity;file.cltbl=map;
      result=f_lseek(&file,CREATE_LINKMAP);
      if(result==FR_NOT_ENOUGH_CORE && map[0]<=capacity)break;
      capacity=map[0];
    }
    if(result==FR_OK && f_size(&file)==expected && capacity>=2){
      const size_t count=(capacity-2)/2;
      auto *items=static_cast<Extent*>(heap_caps_malloc(count*sizeof(Extent),MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT));
      size_t total=0;
      bool valid=items && map[capacity-1]==0;
      for(size_t i=0;valid && i<count;++i){
        const uint64_t clusters=map[1+2*i],start=map[2+2*i];
        const uint64_t sectors=clusters*file.obj.fs->csize;
        const uint64_t sector=file.obj.fs->database+(start-2)*file.obj.fs->csize;
        valid=clusters && start>=2 && sector<card_->csd.capacity &&
              sectors<=card_->csd.capacity-sector && sectors<=SIZE_MAX/512 &&
              total<=SIZE_MAX-size_t(sectors*512);
        if(valid){items[i]={total,size_t(sectors*512),size_t(sector)};total+=items[i].bytes;}
      }
      const size_t cluster_bytes=size_t(file.obj.fs->csize)*512;
      valid=valid && total>=expected && cluster_bytes && total-expected<cluster_bytes;
      if(valid){extents_=items;extent_count_=count;volume_=file.obj.fs->ldrv;}
      else heap_caps_free(items);
    }
    file.cltbl=nullptr;
    f_close(&file);
    heap_caps_free(map);
#endif
  }
  bool read_mapped(size_t offset,uint8_t *out,size_t bytes){
#if FF_FS_REENTRANT
    // Share the filesystem lock with uploads and other FatFs users. The
    // SDMMC transaction mutex alone covers individual commands, while a
    // sector operation also performs status and ready checks afterward.
    const VolumeLock lock(volume_);
    if(!lock.acquired)return false;
#endif
    const Extent *begin=extents_,*end=extents_+extent_count_;
    const auto *extent=std::upper_bound(begin,end,offset,
      [](size_t position,const Extent &item){return position<item.first;});
    if(extent==extents_)return false;
    --extent;
    while(bytes && extent!=end){
      const size_t within=offset-extent->first;
      if(within>=extent->bytes){++extent;continue;}
      const size_t skip=within%512;
      const size_t available=extent->bytes-(within-skip);
      const size_t wanted=std::min(bytes,read_block_size-skip);
      const size_t count=std::min(available/512,(wanted+skip+511)/512);
      if(!count || sdmmc_read_sectors(card_,read_buffer_,extent->sector+within/512,count)!=ESP_OK)return false;
      const size_t copied=std::min(bytes,count*512-skip);
      memcpy(out,read_buffer_+skip,copied);
      out+=copied;offset+=copied;bytes-=copied;
    }
    return bytes==0;
  }
 public:
  CardArt()=default;
  CardArt(const CardArt&)=delete;
  CardArt &operator=(const CardArt&)=delete;
  ~CardArt(){close();}
  bool mount(){
    const std::lock_guard<std::mutex> lock(mount_mutex_);
    if(card_)return true;
    if(esp_timer_get_time()<retry_mount_at_)return false;
    // Retry transient initialization failures on this slot without resetting
    // the shared hosted-radio controller or formatting the card.
    for(unsigned attempt=0;attempt<3;++attempt){
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
      if(esp_task_wdt_status(nullptr)==ESP_OK)esp_task_wdt_reset();
      vTaskDelay(pdMS_TO_TICKS(250));
    }
    retry_mount_at_=esp_timer_get_time()+5000000;
    return false;
  }
  bool space(uint64_t &total,uint64_t &free)const{
    return card_ && esp_vfs_fat_info("/sd",&total,&free)==ESP_OK;
  }
  void close(){
    if(file_>=0)::close(file_);
    heap_caps_free(read_buffer_);read_buffer_=nullptr;
    heap_caps_free(extents_);extents_=nullptr;extent_count_=0;volume_=-1;
    file_=-1;length_=0;path_.clear();
  }
  bool open(const char *path,size_t expected,const uint8_t *digest){
    // Callers reuse the same open, already-verified immutable bank.
    if(file_>=0 && path_==path && length_==expected && !memcmp(verified_,digest,32))return true;
    close();
    if(!card_)return false;
    const int f=::open(path,O_RDONLY);
    if(f<0)return false;
    struct stat info{};
    bool ok=fstat(f,&info)==0 && info.st_size==off_t(expected);
    if(!ok)ESP_LOGW("study_card","Artwork file length check failed, expected %u",unsigned(expected));
    mbedtls_sha256_context ctx;mbedtls_sha256_init(&ctx);
    ok=ok && mbedtls_sha256_starts(&ctx,0)==0;
    // Only the sector buffer needs internal DMA memory. The SHA staging
    // buffer can span fragmented extents in PSRAM without using a second
    // scarce internal allocation while the network worker is running.
    auto *block=static_cast<uint8_t*>(heap_caps_malloc(read_block_size,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT));
    read_buffer_=static_cast<uint8_t*>(heap_caps_aligned_alloc(128,read_block_size,MALLOC_CAP_INTERNAL|MALLOC_CAP_DMA|MALLOC_CAP_8BIT));
    ok=ok && block && read_buffer_;
    if(!block || !read_buffer_)ESP_LOGW("study_card","Artwork verification buffer allocation failed");
    file_=f;length_=expected;
    if(ok)map_extents(path,expected);
    for(size_t n=0;ok && n<expected;){
      size_t take=std::min(read_block_size,expected-n);
      const auto got=read(n,block,take)?ssize_t(take):-1;
      const int result=got==ssize_t(take)?mbedtls_sha256_update(&ctx,block,take):-1;
      ok=got==ssize_t(take) && result==0;
      if(!ok)ESP_LOGW("study_card","Artwork read at %u requested %u received %u SHA status %d",unsigned(n),unsigned(take),unsigned(got),result);
      n+=take;
      if(n%(128*1024)==0){
        if(esp_task_wdt_status(nullptr)==ESP_OK)esp_task_wdt_reset();
        vTaskDelay(1);
      }
    }
    uint8_t actual[32]{};
    if(ok){
      ok=mbedtls_sha256_finish(&ctx,actual)==0 && !memcmp(digest,actual,32);
      if(!ok)ESP_LOGW("study_card","Artwork hash prefix %02x%02x%02x%02x expected %02x%02x%02x%02x",actual[0],actual[1],actual[2],actual[3],digest[0],digest[1],digest[2],digest[3]);
    }
    mbedtls_sha256_free(&ctx);
    heap_caps_free(block);
    if(!ok){ESP_LOGW("study_card","Artwork verification failed");close();return false;}
    path_=path;memcpy(verified_,digest,32);return true;
  }
  bool read(size_t offset,void *dest,size_t bytes){
    if(file_<0 || !read_buffer_ || offset>length_ || bytes>length_-offset)return false;
    auto *out=static_cast<uint8_t*>(dest);
    if(extents_)return read_mapped(offset,out,bytes);
    if(lseek(file_,off_t(offset),SEEK_SET)!=off_t(offset))return false;
    while(bytes){
      // Read complete sectors into aligned internal DMA memory. Direct reads
      // into arbitrary PSRAM offsets otherwise fall back to single sectors.
      const size_t boundary=offset%512;
      const size_t count=std::min(bytes,boundary?512-boundary:read_block_size);
      if(::read(file_,read_buffer_,count)!=ssize_t(count))return false;
      memcpy(out,read_buffer_,count);
      out+=count;offset+=count;bytes-=count;
    }
    return true;
  }
};
}
