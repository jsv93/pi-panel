// Names use the CM5's exact 29px/300 font already present for queue text.
// Prepare one changed row at a time on Music, then reuse it when opened.
#ifdef STUDY_LIVE_CAPTURE
static bool speaker_prewarm_disabled=false;
static int speaker_warm_max_ms=0;
#endif
static bool cache_speakers(int budget=0){
  static int keys[speaker_capacity]{};
  if(!speaker_cache || speaker_cache_dirty)std::fill_n(keys,speaker_capacity,-1);
  const int w=speaker_rects[0][1],h=speaker_rows[0][0][2];
  const size_t bytes=2u*w*h*std::max(1,speaker_count);
  if(!speaker_cache){
    if(budget && heap_caps_get_free_size(MALLOC_CAP_SPIRAM)<bytes+2*1024*1024)return false;
    speaker_cache=static_cast<uint8_t*>(heap_caps_malloc(bytes,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT));
  }
  if(!speaker_cache)return false;
  speaker_cache_dirty=false;
  auto *cache=speaker_cache;
  int row_top=0;
  for(int i=0;i<speaker_count;++i){
    const int variant=speaker_variant(i),key=variant+4*can_transfer(i);const auto *art=speaker_rows[0][variant];
    if(keys[i]==key){row_top+=speaker_height(i);continue;}
    // The renderer is idle here. Stage outside the packed strip so refreshing
    // a single row cannot overwrite its already-cached neighbour's border.
    auto *row=previous_pixels;
    if(!text_image(row,2*w*h,art[0],art[1]))return false;
    const int ax=speaker_rects[0][2];
    if(can_transfer(i) && text_image(scratch,2*(w-ax)*h,speaker_arrows[0][0],speaker_arrows[0][1]))
      for(int y=0;y<h;++y)memcpy(row+2*(y*w+ax),scratch+2*y*(w-ax),2*(w-ax));
    auto *pixels=reinterpret_cast<uint16_t*>(row);
    const int y=variant==3?37:27;
    // Erase only the captured name; preserve subtitle, icons and border.
    for(int j=y;j<y+35;++j)for(int x=50;x<482;++x)pixels[j*w+x]=pixels[j*w+40+(x%4)];
    auto name=library_name_0_0;
#ifdef STUDY_OVERLAY_PALETTES
    name.colour=overlay_artwork.colour(name.bg,name.size,name.colour,name.font,text_palette);
#endif
    name.bg=name.size=0;name.font=queue_track.font;name.rect={50,y,432,35};name.baseline=28;name.align=0;name.spacing=0;
    text_field(row,w,scratch,name,speaker_labels[i],0,h,false);
    memcpy(cache+2u*w*row_top,row+2*w*(i?1:0),2*w*speaker_height(i));
    esp_cache_msync(cache+2u*w*row_top,2*w*speaker_height(i),ESP_CACHE_MSYNC_FLAG_DIR_C2M|ESP_CACHE_MSYNC_FLAG_UNALIGNED);
    keys[i]=key;
    row_top+=speaker_height(i);
    if(budget && --budget==0)return false;
  }
  return true;
}
static void warm_speakers(){
#ifdef STUDY_OVERLAY_PALETTES
  if(current!=media || library_open || queue_open || volume_open || blanked){
    if(speaker_cache && !speakers_open)clear_speaker_cache();
    return;
  }
  if(moving || down || speakers_open || !previous_pixels || !overlay_artwork.ready())return;
#ifdef STUDY_LIVE_CAPTURE
  if(speaker_prewarm_disabled)return;
#endif
  // Preserve the current page's palette/overlay flags while warming offscreen.
  const bool frame=overlay_frame;
#ifdef STUDY_LIVE_CAPTURE
  const auto started=clock_ms();
#endif
  {TextPaletteScope colours(palette.selection(),false);cache_speakers(1);}
#ifdef STUDY_LIVE_CAPTURE
  speaker_warm_max_ms=std::max(speaker_warm_max_ms,int(clock_ms()-started));
#endif
  overlay_frame=frame;
#endif
}
static void paint_speaker_rows(uint8_t *dest){
  const int x=speaker_rects[0][0],w=speaker_rects[0][1],h=speaker_rows[0][0][2];
  int top=speaker_top-speaker_scroll,source=0;
  const int total=speaker_count?speaker_count*(h-1)+1:0;
  const int rows=std::min(speaker_end-speaker_top,total-speaker_scroll);
  if(rows>0 && scanout.copy_rect(dest,speaker_cache,x,speaker_top,speaker_scroll,w,rows,w,total,0)){
    speaker_painted_scroll=speaker_scroll;return;
  }
  for(int i=0;i<speaker_count;++i){
    const int rows=speaker_height(i);
    for(int y=std::max(0,speaker_top-top);y<rows && y+top<speaker_end;++y)
      memcpy(dest+2*((top+y)*width+x),speaker_cache+2*((source+y)*w),2*w);
    top+=rows;source+=rows;
  }
  speaker_painted_scroll=speaker_scroll;
}
static void animate_speakers(){
  if(!speakers_open || current!=media || blanked || moving || !speaker_cache)return;
  const auto now=clock_ms();const int dt=speaker_frame_at?std::clamp(int(now-speaker_frame_at),0,100):16;
  if(dt<16)return;
  auto *slot=scanout.acquire(false,true);if(!slot)return;
  speaker_frame_at=now;
  if(!down && std::abs(speaker_velocity)>12){
    const float damping=std::exp(-dt/325.f);
    speaker_position+=speaker_velocity*.325f*(1-damping);speaker_velocity*=damping;
    speaker_scroll=std::clamp(int(std::lround(speaker_position)),0,speaker_max_scroll);
    if(speaker_position<=0 || speaker_position>=speaker_max_scroll)speaker_velocity=0;
  }
  if(speaker_scroll==speaker_painted_scroll)return;
  // Keep chrome and margins stationary. No SD reads or decompression here.
  if(slot->page!=revision)scanout.copy_pixels(slot->pixels,page_pixels,page_bytes);
  const bool copied=scanout.copy_rect(slot->pixels,speaker_cache,speaker_rects[0][0],speaker_top,speaker_scroll,
      speaker_rects[0][1],speaker_end-speaker_top,speaker_rects[0][1],speaker_max_scroll+speaker_end-speaker_top,0);
  if(!copied)paint_speaker_rows(slot->pixels);
  if(scanout.present(slot,copied?0:speaker_top,copied?1:speaker_end)){
    slot->page=revision;slot->lamp_background=false;speaker_painted_scroll=speaker_scroll;
  }
}
