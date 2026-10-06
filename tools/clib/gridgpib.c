/*
 * gridgpib.c - C interface to the GRIDGPIB resident GPIB driver (Grid-OS)
 * OpenWatcom C, 16-bit DOS, any memory model.
 */
#include <dos.h>
#include <i86.h>
#include <string.h>
#include "gridgpib.h"

int gg_lasterr = 0;
static int gg_int = 0;
static char gg_scratch[128];              /* discard area for overflow */

static int gg_call(union REGS *r, struct SREGS *s)
{
    if (gg_int == 0) { gg_lasterr = GG_ENODRIVER; return GG_ENODRIVER; }
    int86x(gg_int, r, r, s);
    if (r->x.cflag) {
        gg_lasterr = r->x.ax ? r->x.ax : GG_ETIMEOUT;
        return gg_lasterr;
    }
    return GG_OK;
}

int gg_open(void)
{
    int n;
    for (n = 0x60; n <= 0x66; n++) {
        unsigned char far *p = (unsigned char far *)_dos_getvect(n);
        if (p != 0 && _fmemcmp(p + 2, "GRIDGPIB", 8) == 0) {
            union REGS r; struct SREGS s;
            gg_int = n;
            segread(&s);
            r.h.ah = 0x00;
            if (gg_call(&r, &s) == GG_OK && r.x.ax == 0x4747) return GG_OK;
            gg_int = 0;
        }
    }
    gg_lasterr = GG_ENODRIVER;
    return GG_ENODRIVER;
}

int gg_vector(void) { return gg_int; }

static int gg_simple(unsigned char fn, int addr, unsigned bx_extra)
{
    union REGS r; struct SREGS s;
    segread(&s);
    r.h.ah = fn;
    r.x.bx = (addr < 0) ? 0xFF : (unsigned)addr;
    if (bx_extra) r.x.bx = bx_extra;
    return gg_call(&r, &s);
}

int gg_init(void) { return gg_simple(0x01, 0, 0); }

int gg_write(int addr, const void far *data, unsigned len, int eoi)
{
    union REGS r; struct SREGS s;
    segread(&s);
    r.h.ah = 0x02;
    r.h.al = eoi ? 1 : 0;
    r.x.bx = addr;
    r.x.cx = len;
    s.ds = FP_SEG(data);
    r.x.si = FP_OFF(data);
    return gg_call(&r, &s);
}

int gg_read(int addr, void far *buf, unsigned max,
            unsigned *count, int *endr, int stop_lf)
{
    union REGS r; struct SREGS s;
    int e;
    segread(&s);
    r.h.ah = 0x03;
    r.h.al = stop_lf ? 1 : 0;
    r.x.bx = addr;
    r.x.cx = max;
    s.es = FP_SEG(buf);
    r.x.di = FP_OFF(buf);
    e = gg_call(&r, &s);
    if (count) *count = (e == GG_OK) ? r.x.cx : 0;
    if (endr) *endr = (e == GG_OK) ? r.h.dl : 0;
    return e;
}

int gg_puts(int addr, const char *cmd)
{
    char line[256];
    unsigned n = strlen(cmd);
    if (n > sizeof(line) - 3) { gg_lasterr = GG_EPARAM; return -GG_EPARAM; }
    memcpy(line, cmd, n);
    line[n++] = '\r';
    line[n++] = '\n';
    {
        int e = gg_write(addr, (const void far *)line, n, 1);
        return e ? -e : (int)n;
    }
}

/* after a GG_END_FULL read: pull the rest of the message and drop it */
static void gg_discard_rest(int addr)
{
    unsigned c; int endr = GG_END_FULL;
    while (endr == GG_END_FULL) {
        if (gg_read(addr, (void far *)gg_scratch, sizeof(gg_scratch),
                    &c, &endr, 1) != GG_OK) break;
    }
}

int gg_gets(int addr, char *buf, int size)
{
    unsigned c = 0; int endr = 0, e;
    if (size < 1) { gg_lasterr = GG_EPARAM; return -GG_EPARAM; }
    e = gg_read(addr, (void far *)buf, size - 1, &c, &endr, 1);
    buf[e ? 0 : c] = '\0';
    if (e) return -e;
    if (endr == GG_END_FULL) gg_discard_rest(addr);
    return (int)c;
}

int gg_query(int addr, const char *cmd, char *buf, int size)
{
    union REGS r; struct SREGS s;
    char line[256];
    unsigned n = strlen(cmd);
    int e;
    if (size < 1 || n > sizeof(line) - 3) { gg_lasterr = GG_EPARAM; return -GG_EPARAM; }
    memcpy(line, cmd, n);
    line[n++] = '\r';
    line[n++] = '\n';
    segread(&s);
    r.h.ah = 0x04;
    r.h.al = 1;                           /* stop at LF */
    r.x.bx = addr;
    r.x.cx = n;
    s.ds = FP_SEG((void far *)line);
    r.x.si = FP_OFF((void far *)line);
    s.es = FP_SEG((void far *)buf);
    r.x.di = FP_OFF((void far *)buf);
    r.x.dx = size - 1;
    e = gg_call(&r, &s);
    if (e) { buf[0] = '\0'; return -e; }
    buf[r.x.cx] = '\0';
    if (r.h.dl == GG_END_FULL) gg_discard_rest(addr);
    return (int)r.x.cx;
}

int gg_spoll(int addr, unsigned char *status)
{
    union REGS r; struct SREGS s;
    int e;
    segread(&s);
    r.h.ah = 0x05;
    r.x.bx = addr;
    e = gg_call(&r, &s);
    if (status) *status = e ? 0 : r.h.al;
    return e;
}

int gg_clear(int addr)   { return gg_simple(0x06, addr, 0); }
int gg_trigger(int addr) { return gg_simple(0x07, addr, 0); }
int gg_remote(int addr)  { return gg_simple(0x08, addr, 0); }
int gg_local(int addr)   { return gg_simple(0x09, addr, 0); }

int gg_timeout(unsigned ms)
{
    union REGS r; struct SREGS s;
    segread(&s);
    r.h.ah = 0x0A;
    r.x.bx = ms;
    if (gg_call(&r, &s)) return -gg_lasterr;
    return (int)r.x.ax;
}

int gg_srq(void)
{
    union REGS r; struct SREGS s;
    segread(&s);
    r.h.ah = 0x0B;
    if (gg_call(&r, &s)) return 0;
    return r.x.ax ? 1 : 0;
}

int gg_stats(unsigned *recoveries, unsigned *timeouts, unsigned *resident)
{
    union REGS r; struct SREGS s;
    int e;
    segread(&s);
    r.h.ah = 0x0C;
    e = gg_call(&r, &s);
    if (recoveries) *recoveries = e ? 0 : r.x.ax;
    if (timeouts)   *timeouts   = e ? 0 : r.x.cx;
    if (resident)   *resident   = e ? 0 : r.x.dx;
    return e;
}

const char *gg_errstr(int err)
{
    if (err < 0) err = -err;
    switch (err) {
    case GG_OK:        return "OK";
    case GG_ETIMEOUT:  return "TIME OUT";
    case GG_ENOLISTEN: return "NO LISTENER";
    case GG_ENOCTRL:   return "NOT CONTROLLER";
    case GG_EFUNC:     return "BAD FUNCTION";
    case GG_ENODATA:   return "TIME OUT - NO DATA";
    case GG_EBUSY:     return "DRIVER BUSY";
    case GG_ENODRIVER: return "GRIDGPIB NOT LOADED";
    case GG_EPARAM:    return "BAD PARAMETER";
    }
    return "UNKNOWN ERROR";
}
