/*
 * gridgpib.h - C interface to the GRIDGPIB resident GPIB driver (Grid-OS)
 * OpenWatcom C, 16-bit DOS, any memory model.
 *
 * The driver (GRIDGPIB.COM) must be loaded first.  Every call blocks only
 * until the bus transaction is complete (or times out) - no sleeps needed.
 */
#ifndef GRIDGPIB_H
#define GRIDGPIB_H

#define GG_OK         0
#define GG_ETIMEOUT   1   /* handshake timed out                     */
#define GG_ENOLISTEN  2   /* nobody listening at that address        */
#define GG_ENOCTRL    3   /* not controller in charge / no chip      */
#define GG_EFUNC      4   /* bad driver function                     */
#define GG_ENODATA    5   /* read: device sent nothing               */
#define GG_EBUSY      6   /* driver re-entered                       */
#define GG_ENODRIVER 100  /* GRIDGPIB not loaded                     */
#define GG_EPARAM    101  /* bad argument                            */

#define GG_END_EOI    1   /* read ended on EOI                       */
#define GG_END_LF     2   /* read ended on LF                        */
#define GG_END_FULL   4   /* buffer full - more data waiting         */
#define GG_END_TMO    8   /* timeout after some data                 */

#define GG_ALL      (-1)  /* for gg_clear / gg_local / gg_remote     */

extern int gg_lasterr;    /* error code of the last failing call     */

int  gg_open(void);       /* find the driver: 0 = OK, GG_ENODRIVER   */
int  gg_vector(void);     /* interrupt number in use (0 = not open)  */
int  gg_init(void);       /* IFC + REN: take control of the bus      */

/* raw byte transfer */
int  gg_write(int addr, const void far *data, unsigned len, int eoi);
int  gg_read(int addr, void far *buf, unsigned max,
             unsigned *count, int *endr, int stop_lf);

/* message level: commands get CR LF + EOI appended (like Driver488's
 * default EOL OUT); replies are read whole, NUL-terminated, never split -
 * anything that does not fit is read and discarded so the next
 * transaction starts clean.  Return value: bytes stored, or -error.   */
int  gg_puts(int addr, const char *cmd);
int  gg_gets(int addr, char *buf, int size);
int  gg_query(int addr, const char *cmd, char *buf, int size);

int  gg_spoll(int addr, unsigned char *status);
int  gg_clear(int addr);          /* SDC, or DCL with GG_ALL          */
int  gg_trigger(int addr);        /* GET                              */
int  gg_remote(int addr);         /* REN + address, GG_ALL = REN only */
int  gg_local(int addr);          /* GTL, GG_ALL = drop REN           */
int  gg_timeout(unsigned ms);     /* per byte; returns old value (ms) */
int  gg_srq(void);                /* 1 if SRQ asserted since last call*/
int  gg_stats(unsigned *recoveries, unsigned *timeouts, unsigned *resident);
const char *gg_errstr(int err);

#endif
