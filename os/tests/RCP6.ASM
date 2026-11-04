; RCP6.RUN - RCTEST.RUN for API 6, reading with UI_POLL (UI_EVENT's look
; without the wait, which KMW's mw_got never sees): a right click must not
; reach it, with multitasking on too (test_mt t_exmenu)
%define RC_API 6
%define RC_POLL
%include "RCTEST.ASM"
