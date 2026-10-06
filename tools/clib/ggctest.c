/* ggctest.c - exercises gridgpib.c and the TM5000 gpib.c back end */
#include "gpib.h"
#include "gridgpib.h"

int  gpib_error = 0;
char g_error_msg[64];
SystemState *g_system = 0;

static void show(const char *what, int n, const char *buf)
{
    printf("%-22s %4d  [%s]\n", what, n, buf);
}

int main(void)
{
    char buf[GPIB_BUFFER_SIZE];
    unsigned char st;
    float v;
    int n;

    if (init_gpib_system() < 0) return 1;

    n = gg_query(6, "ID?", buf, sizeof(buf));           show("gg_query 6 ID?", n, buf);
    n = gg_query(6, "SET?", buf, 12);                    show("gg_query SET? (12)", n, buf);
    n = gg_query(6, "ID?", buf, sizeof(buf));            show("next query clean?", n, buf);

    gpib_write(16, "FUNCT DCV");
    n = gpib_read(16, buf, sizeof(buf));                 show("gpib_read 16", n, buf);
    n = gpib_read_float_dm5010(28, &v);
    printf("%-22s %4d  %g\n", "read_float 28", n, v);

    ieee_write("output 18;*IDN?\r\n");
    ieee_write("enter 18\r\n");
    n = ieee_read(buf, 10);                              show("ieee_read (10)", n, buf);
    n = ieee_read(buf, sizeof(buf));                     show("ieee_read rest", n, buf);
    ieee_write("spoll 18\r\n");
    n = ieee_read(buf, sizeof(buf));                     show("SPOLL 18", n, buf);
    ieee_write("status\r\n");
    n = ieee_read(buf, sizeof(buf));                     show("STATUS", n, buf);
    ieee_write("output 9;ID?\r\n");                      /* nobody at 9 */
    ieee_write("status\r\n");
    n = ieee_read(buf, sizeof(buf));                     show("STATUS after bad", n, buf);
    check_gpib_error();
    printf("gpib_error after check: %d\n", gpib_error);
    ieee_write("*OPC?\r\n");
    ieee_write("status\r\n");
    n = ieee_read(buf, sizeof(buf));                     show("STATUS after junk", n, buf);
    ieee_write("abort\r\n");
    ieee_write("hello\r\n");
    n = ieee_read(buf, sizeof(buf));                     show("HELLO", n, buf);
    n = ieee_spoll(29, &st);
    printf("%-22s %4d  %u\n", "ieee_spoll 29", n, st);
    gpib_remote(29);
    gpib_local(29);
    gpib_clear(29);
    ieee_write("time out 0.5\r\n");
    printf("timeout now %d ms\n", gg_timeout(0));
    gpib_local(GG_ALL);
    printf("done\n");
    return 0;
}
