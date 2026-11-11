; NOMATCH.COM (test_kernel t_nomatch): FIND FIRST that finds nothing,
; and the searches next to it: a directory that isn't there, a bad name, a
; hidden file without the bit, an empty directory.  Each line: fn, the
; name, ok or the error.  test_kernel holds the answers GRiD MS-DOS 3.30
; gives (CX is in the table, not printed)
%include "PROBE.INC"
; the cases: fn, name 1, name 2, CX (test_kernel t_nomatch makes the files and
; directories they name)
tests   dw 4E00h, p0, 0, 00h
        dw 4E00h, p1, 0, 00h
        dw 4E00h, p2, 0, 00h
        dw 4E00h, p3, 0, 00h
        dw 4E00h, p4, 0, 00h
        dw 4E00h, p5, 0, 00h
        dw 4E00h, p6, 0, 00h
        dw 4E00h, p7, 0, 00h
        dw 4E00h, p8, 0, 00h
        dw 4E00h, p9, 0, 00h
        dw 4E00h, p10, 0, 00h
        dw 4E00h, p11, 0, 00h
        dw 4E00h, p12, 0, 00h
        dw 4E00h, p13, 0, 00h
        dw 4E00h, p14, 0, 00h
        dw 4E00h, p15, 0, 00h
        dw 4E00h, p16, 0, 00h
        dw 4E00h, p17, 0, 00h
        dw 4E00h, p18, 0, 00h
        dw 4E00h, p19, 0, 00h
        dw 4E00h, p20, 0, 00h
        dw 4E00h, p21, 0, 00h
        dw 4E00h, p22, 0, 00h
        dw 4E00h, p6, 0, 10h
        dw 4E00h, p23, 0, 10h
        dw 4E00h, p0, 0, 10h
        dw 4E00h, p11, 0, 10h
        dw 4E00h, p8, 0, 06h
        dw 4E00h, p9, 0, 06h
        dw 4E00h, p0, 0, 06h
        dw 4E00h, p1, 0, 06h
        dw 4E00h, p0, 0, 08h
        dw 4E00h, p6, 0, 08h
        dw 0
p0      db 'NOSUCH.TXT', 0
p1      db 'Z*.*', 0
p2      db 'A.B\N?L', 0
p3      db 'A.B\X.TXT', 0
p4      db 'A.B\NOSUCH', 0
p5      db 'E.F\*.TXT', 0
p6      db 'E.F\*.*', 0
p7      db 'E.F\NOSUCH', 0
p8      db 'HID.TXT', 0
p9      db 'HS.TXT', 0
p10     db 'SYS.TXT', 0
p11     db 'A.B', 0
p12     db '*.TXT', 0
p13     db '*.*', 0
p14     db 'NOSUCH\*.*', 0
p15     db 'A.TXT\*.*', 0
p16     db 'A?B\*.*', 0
p17     db 'A.B.C', 0
p18     db 'A.B\X.Y.Z', 0
p19     db '', 0
p20     db 'A:NOSUCH', 0
p21     db '\A.B\..\NOSUCH', 0
p22     db 'E.F\..\A.TXT', 0
p23     db 'E.F\Z*.*', 0
