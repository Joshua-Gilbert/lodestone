# main without #151's floppy guard (for the variac test)

The 1520's restarts turned out to be its power supply sagging under load
(a variac a few volts up stops them), so #151's rule -- an EMS page
register written during floppy DMA resets the 1520 -- may never have been
real: its evidence was breadcrumbs from those brownouts. This is main
(the same as merged) with the guard switched off, same sizes elsewhere:
mt_eout writes at once, mt_dok and mt_i67 never hold back for a floppy's
owner. In pcemu, which models the rule, t_dmaems now fails as it should.

On stable power (the variac), boot a floppy with LODE.SYS and LODEMT.SYS
from here (main's TERM.RUN from ROM 1, main's CLAUDE.COM 1.15 here),
MULTITASK=1, and try the old triggers: Return on CLAUDE.COM, CODE-P
windows and their resizes, pictures opened and closed from the Executive
while a terminal window is open. No restart: the guard goes (its own PR).
`crashlog/` is the same with CRASHLOG, in case it does restart.
