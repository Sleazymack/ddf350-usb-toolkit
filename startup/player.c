/* Original, bounded startup animation player for the exact audited DDF-350 2.0.5.
 * No interrupt masks, Flash writes, RF calls, new task, or arbitrary global RAM.
 * Native ABI checked against the user's original image and LVGL 8 structures.
 * https://github.com/lvgl/lvgl/tree/v8.3.0/src/draw
 */
typedef unsigned char u8;
typedef unsigned short u16;
typedef unsigned int u32;
typedef int i32;
#define API(offset, result, args) ((result (*) args)(0x08005001u+(offset)))
#define OFF(type,field) __builtin_offsetof(type,field)
typedef struct {u32 header,size;const void *data;} Image;
typedef struct Decoder {void *info,*open,*line,*close,*user;} Decoder;
typedef struct {Decoder *decoder;const Image *src;u16 color,pad;i32 frame_id;u8 type,pad2[3];u32 header;const void *pixels;u32 time;const char *error;void *user;} Session;
typedef struct Timer {u32 period,last;void *callback,*user;i32 repeat;u32 flags;} Timer;
typedef struct Context {
    u32 magic,active,dead;
    void *root,*image;
    Timer *timer;Decoder *decoder;
    const u8 *asset,*end,*next;
    u8 *pixels;
    u32 frame,frames,bytes,sw,sh;
    Image descriptor;
#ifdef DDF_SIMPLE_LOOP
    u32 cycles_left;
#endif
} Context;
typedef struct {u32 magic,asset,asset_size,width,height,top,reserved[2];} Config;
__attribute__((used,section(".config"))) const volatile Config boot_config={0x53475031,0,0,240,275,22,{0,0}};
__attribute__((used)) const u32 boot_context_size=sizeof(Context);
__attribute__((used)) const u32 boot_context_offsets[]={OFF(Context,active),OFF(Context,dead),OFF(Context,root),OFF(Context,image),OFF(Context,timer),OFF(Context,decoder),OFF(Context,pixels),OFF(Context,frame),OFF(Context,next),OFF(Context,descriptor),OFF(Context,sw),OFF(Context,sh)};
_Static_assert(sizeof(Session)==40 && OFF(Session,header)==20 && OFF(Session,user)==36,"native session ABI");
_Static_assert(sizeof(Decoder)==20 && sizeof(Timer)==24,"native callback ABI");
static u32 rd16(const u8*p){return (u32)p[0]|((u32)p[1]<<8);}
static u32 rd32(const u8*p){return rd16(p)|(rd16(p+2)<<16);}
static void zero(void*p,u32 n){volatile u8*d=p;while(n--)*d++=0;}
static void *alloc(u32 n){return API(0x4a9b8,void*,(u32))(n);}
static void release(void*p){if(p)API(0x4ab54,void,(void*))(p);}
static void delete_root(void*p){API(0x4c21c,void,(void*))(p);}
static void *new_object(const void*type,void*parent){
    void *obj=API(0x4bf0c,void*,(const void*,void*))(type,parent);
    if(obj)API(0x4bffc,void,(void*))(obj);
    return obj;
}
static void undecorate(void *obj){
    static const u32 props[]={0x21,0x1032,0x840,0x83a,0x1010,0x1011,0x1012,0x1013};
    for(u32 n=0;n<8;n++)API(0x500c4,void,(void*,u32,u32,u32))(obj,props[n],0,0);
}
static int info(Decoder*d,const Image*src,u32*header){
    Context*c=d->user;
    if(!c || c->magic!=0x47494631 || !c->active || src!=&c->descriptor)return 0;
    /* Encoded source is RAW, but every emitted line is decoded RGB565.
     * Report TRUE_COLOR (4), so native drawing allocates two bytes/pixel. */
    *header=(c->descriptor.header&~31u)|4u;return 1;
}
static int open_image(Decoder*d,Session*s){
    Context*c=d->user;
    if(!c || !c->active || s->src!=&c->descriptor)return 0;
    s->header=(c->descriptor.header&~31u)|4u;s->pixels=0;s->user=c;return 1;
}
static int read_line(Decoder*d,Session*s,short x,short y,short len,u8*out){
    Context*c=d->user;
    u32 width=boot_config.width,height=boot_config.height;
    if(!c || !c->active || !c->pixels || s->src!=&c->descriptor || x<0 || y<0 || len<0 || (u32)x+(u32)len>width || (u32)y>=height)return 0;
    u32 row=((u32)y*c->sh/height)*c->sw;
    for(u32 n=0;n<(u32)len;n++){
        u32 pixel=row+((u32)x+n)*c->sw/width;
        u8 pair=c->pixels[pixel>>1];u32 index=(pixel&1)?pair&15:pair>>4;
        const u8 *color=c->asset+20+index*2;
        /* Native RGB565 API is byte-swapped; emit its actual memory order. */
        out[n*2]=color[1];out[n*2+1]=color[0];
    }
    return 1;
}
static void close_image(Decoder*d,Session*s){(void)d;s->user=0;}
static void deleted(void *event){
    Context*c=API(0x46554,Context*,(void*))(event);
    if(c && c->magic==0x47494631)c->dead=1;
}
/* Descriptor/context remain registered and inactive (~100 bytes) after boot.
 * LVGL may retain decoder sessions in its image cache. Keeping these small
 * owners alive prevents a dangling cache pointer; the 9408-byte frame is freed.
 */
static void finish(Context*c){
    Timer*t=c->timer;c->timer=0;c->active=0;
    if(c->root && !c->dead)delete_root(c->root);
    c->root=0;c->image=0;
    release(c->pixels);c->pixels=0;
    if(t)API(0x53cdc,void,(Timer*))(t);
}
__attribute__((noinline)) static int decode_frame(Context*c){
    const u8*p=c->next;
    if(c->frame>=c->frames || p>c->end || (u32)(c->end-p)<6)return 0;
    u32 duration=rd16(p),length=rd32(p+2);p+=6;
#ifdef DDF_SIMPLE_LOOP
    if(duration!=50)return 0;
#endif
    if(duration<10 || duration>1000 || length>(u32)(c->end-p))return 0;
    const u8*end=p+length;u32 position=0;
    while(p<=end && (u32)(end-p)>=4){
        u32 skip=rd16(p),count=rd16(p+2);p+=4;
        if(skip==65535 && count==0){
            if(p!=end)return 0;
            c->next=end;c->frame++;
            if(c->timer)c->timer->period=duration;
            return (int)duration;
        }
        if(skip>c->bytes-position)return 0;
        position+=skip;
        if(!count || count>c->bytes-position || count>(u32)(end-p))return 0;
        for(u32 n=0;n<count;n++)c->pixels[position+n]=p[n];
        position+=count;p+=count;
    }
    return 0;
}
static void tick(Timer*t){
    Context*c=t->user;
    if(!c || c->magic!=0x47494631){API(0x53cdc,void,(Timer*))(t);return;}
#ifdef DDF_SIMPLE_LOOP
    /* First delta in the stored cycle is relative to an all-zero image. */
    if(!c->dead && c->frame==c->frames && c->next==c->end && c->cycles_left>1){
        --c->cycles_left;
        zero(c->pixels,c->bytes);
        c->next=c->asset+52;
        c->frame=0;
    }
#endif
    if(c->dead || c->frame>=c->frames || !decode_frame(c)){finish(c);return;}
    API(0x4ed80,void,(void*))(c->image); /* lv_obj_invalidate */
}
static void start(void){
    if(boot_config.magic!=0x53475031 || boot_config.asset_size<52 || boot_config.asset_size>310000 || boot_config.width!=240 || boot_config.height!=275 || boot_config.top!=22)return;
    if(boot_config.asset<0x080a8000 || boot_config.asset>=0x080f5000 || boot_config.asset_size>0x080f5000-boot_config.asset)return;
    /* Preserve boot warnings/alternate startup modes. */
    if(*(volatile u8*)0x200005b0!=1 || !*(volatile void**)0x200005ac)return;
    const u8 *a=(const u8*)boot_config.asset;
#ifdef DDF_SIMPLE_LOOP
    if(rd32(a)!=0x4c464444 || rd32(a+4)!=0x31504f4f || rd16(a+12)!=10)return; /* DDFLOOP1 */
#else
    if(rd32(a)!=0x41464444 || rd32(a+4)!=0x00314d4e)return; /* DDFANM1\0 */
#endif
    u32 w=rd16(a+8),h=rd16(a+10),frames=rd16(a+12),bytes=rd32(a+16);
    if(w<16 || w>128 || (w&1) || h<16 || h>160 || frames<1 || frames>40 || rd16(a+14)!=16 || bytes!=w*h/2 || bytes>10240)return;
    Context*c=alloc(sizeof(Context));if(!c)return;zero(c,sizeof(Context));
#ifdef DDF_SIMPLE_LOOP
    c->cycles_left=8;
#endif
    c->magic=0x47494631;c->pixels=alloc(bytes);
    if(!c->pixels){release(c);return;}
    zero(c->pixels,bytes);
    void *probe=alloc(2048);
    if(!probe){release(c->pixels);release(c);return;}release(probe);
    c->asset=a;c->end=a+boot_config.asset_size;c->next=a+52;c->sw=w;c->sh=h;c->frames=frames;c->bytes=bytes;
    if(!decode_frame(c))goto failed;
    /* The native welcome finishes after ~1-2 s. Use the persistent top layer
     * so the complete clip remains visible while the dashboard starts below.
     * This is a GUI overlay, not a blocking boot or RF delay. */
    void*parent=API(0x42be0,void*,(void*))(0);if(!parent)goto failed;
    c->root=new_object((void*)0x0809b558,parent);if(!c->root)goto failed;
    undecorate(c->root);
    API(0x50244,void,(void*,short,short))(c->root,240,320);
    API(0x501f2,void,(void*,short,short))(c->root,0,0);
    API(0x50500,void,(void*,u16,u32))(c->root,0,0);
    API(0x5058a,void,(void*,u8,u32))(c->root,255,0);
    c->image=new_object((void*)0x0809be2c,c->root);if(!c->image)goto failed;
    if(!API(0x4b5b0,void*,(void*,void*,u32,void*))(c->root,deleted,33,c))goto failed;
    c->decoder=API(0x480ec,Decoder*,(void))();if(!c->decoder)goto failed;
    c->decoder->info=info;c->decoder->open=open_image;c->decoder->line=read_line;c->decoder->close=close_image;c->decoder->user=c;
    c->descriptor.header=1|(240u<<10)|(275u<<21);c->descriptor.size=sizeof(Context);c->descriptor.data=c;
    c->active=1;
    API(0x4881c,void,(void*,const Image*))(c->image,&c->descriptor);
    API(0x501f2,void,(void*,short,short))(c->image,0,22);
    c->timer=API(0x53c98,Timer*,(void*,u32,void*))(tick,rd16(a+52),c);
    if(!c->timer)finish(c);
    return;
failed:
    if(c->root)delete_root(c->root);
    release(c->pixels);release(c);
}
__attribute__((used,noinline)) void boot_stop_all(void){
    void *list=(void*)0x2000bcc0;
    Decoder*d=API(0x2fb16,Decoder*,(void*))(list);
    for(u32 n=0;d && n<64;n++){
        if(d->info==(void*)info){Context*c=d->user;if(c && c->magic==0x47494631 && c->active)finish(c);}
        d=API(0x2fb46,Decoder*,(void*,void*))(list,d);
    }
}
__attribute__((used,section(".text.boot_start"))) u32 boot_start(void){
    u32 result=API(0x5b2d0,u32,(void))();start();return result;
}
__attribute__((used,naked)) void boot_cleanup_hook(void){
    __asm__ volatile("push {r0-r3,r4,lr}\nbl boot_stop_all\npop.w {r0-r3,r4,lr}\nmovw r12,#0x5465\nmovt r12,#0x0801\nbx r12");
}
