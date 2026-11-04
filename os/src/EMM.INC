; =====================================================================
;  EMM.INC - is there an EMS manager on INT 67h?  (the Executive's info
;  line, System's Memory page)
;
;  ems_mgr -> CF if not.  It looks for 'EMMXXXX0' at offset 0Ah of the
;  INT 67h vector's segment, as programs do: Lodestone's own manager
;  (KEMS.INC) is there whenever there is EMS.  Never call INT 67h without
;  it: with no manager the vector may point anywhere.  DS = the caller's
;  data (s_emm); AX, BX, CX, SI, DI change (ES kept).
; =====================================================================
ems_mgr:
        push    es
        mov     ax, 3567h
        int     21h
        mov     di, 0Ah
        mov     si, s_emm
        mov     cx, 8
        repe    cmpsb
        pop     es
        je      .x
        stc
.x:     ret
s_emm   db 'EMMXXXX0'
