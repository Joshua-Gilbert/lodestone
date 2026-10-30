; NULDIR.COM (test_kernel t_nul): OPEN, CREATE and CREATE NEW of a
; device's name after a directory that is there, is a file, or isn't
; there ("IF EXIST DIR\NUL"), or after \DEV\.  Each line: fn, the
; name, ok or the error.  test_kernel holds the answers GRiD MS-DOS
; 3.30 gives
%include "PROBE.INC"
; X15: a second dot (A.TXT, B.TXT, A.B\X.TXT and E.F empty are there)
tests   dw 3D00h, p0, 0, 0
        dw 3D00h, p1, 0, 0
        dw 3D00h, p2, 0, 0
        dw 3D00h, p3, 0, 0
        dw 3D00h, p4, 0, 0
        dw 3D00h, p5, 0, 0
        dw 3D00h, p6, 0, 0
        dw 3D00h, p7, 0, 0
        dw 3D00h, p8, 0, 0
        dw 3D00h, p9, 0, 0
        dw 3D00h, p10, 0, 0
        dw 3D00h, p11, 0, 0
        dw 3D00h, p12, 0, 0
        dw 3D00h, p13, 0, 0
        dw 3D00h, p14, 0, 0
        dw 3D00h, p15, 0, 0
        dw 3D00h, p16, 0, 0
        dw 3D00h, p17, 0, 0
        dw 3D00h, p18, 0, 0
        dw 3D00h, p19, 0, 0
        dw 3D00h, p20, 0, 0
        dw 3D00h, p21, 0, 0
        dw 3D00h, p22, 0, 0
        dw 3D00h, p23, 0, 0
        dw 3D00h, p24, 0, 0
        dw 3D00h, p25, 0, 0
        dw 3C00h, p0, 0, 0
        dw 3C00h, p1, 0, 0
        dw 3C00h, p2, 0, 0
        dw 3C00h, p3, 0, 0
        dw 3C00h, p4, 0, 0
        dw 3C00h, p5, 0, 0
        dw 3C00h, p6, 0, 0
        dw 3C00h, p7, 0, 0
        dw 3C00h, p8, 0, 0
        dw 3C00h, p9, 0, 0
        dw 3C00h, p10, 0, 0
        dw 3C00h, p11, 0, 0
        dw 3C00h, p12, 0, 0
        dw 3C00h, p13, 0, 0
        dw 3C00h, p14, 0, 0
        dw 3C00h, p15, 0, 0
        dw 3C00h, p16, 0, 0
        dw 3C00h, p17, 0, 0
        dw 3C00h, p18, 0, 0
        dw 3C00h, p19, 0, 0
        dw 3C00h, p20, 0, 0
        dw 3C00h, p21, 0, 0
        dw 3C00h, p22, 0, 0
        dw 3C00h, p23, 0, 0
        dw 3C00h, p24, 0, 0
        dw 3C00h, p25, 0, 0
        dw 5B00h, p0, 0, 0
        dw 5B00h, p1, 0, 0
        dw 5B00h, p2, 0, 0
        dw 5B00h, p3, 0, 0
        dw 5B00h, p4, 0, 0
        dw 5B00h, p5, 0, 0
        dw 5B00h, p6, 0, 0
        dw 5B00h, p7, 0, 0
        dw 5B00h, p8, 0, 0
        dw 5B00h, p9, 0, 0
        dw 5B00h, p10, 0, 0
        dw 5B00h, p11, 0, 0
        dw 5B00h, p12, 0, 0
        dw 5B00h, p13, 0, 0
        dw 5B00h, p14, 0, 0
        dw 5B00h, p15, 0, 0
        dw 5B00h, p16, 0, 0
        dw 5B00h, p17, 0, 0
        dw 5B00h, p18, 0, 0
        dw 5B00h, p19, 0, 0
        dw 5B00h, p20, 0, 0
        dw 5B00h, p21, 0, 0
        dw 5B00h, p22, 0, 0
        dw 5B00h, p23, 0, 0
        dw 5B00h, p24, 0, 0
        dw 5B00h, p25, 0, 0
        dw 0
p0      db 'NOSUCH\NUL', 0
p1      db 'A.B\NUL', 0
p2      db 'A.TXT\NUL', 0
p3      db '\NUL', 0
p4      db 'NUL', 0
p5      db 'A:NUL', 0
p6      db 'A:\NUL', 0
p7      db 'NOSUCH\CON', 0
p8      db 'A.B\CON', 0
p9      db 'A.B\NUL.TXT', 0
p10     db 'NOSUCH\NUL.TXT', 0
p11     db 'NOSUCH\SUB\NUL', 0
p12     db 'A.B\..\NUL', 0
p13     db 'A.B\.\NUL', 0
p14     db 'A.B\NOSUCH\NUL', 0
p15     db 'E.F\NUL', 0
p16     db '\DEV\NUL', 0
p17     db '\DEV\CON', 0
p18     db 'A:\DEV\NUL', 0
p19     db '\DEV\NUL.TXT', 0
p20     db 'DEV\NUL', 0
p21     db '\DEV\SUB\NUL', 0
p22     db 'A.B\NUL.X.Y', 0
p23     db 'A.B\NUL.*', 0
p24     db 'Q:NUL', 0
p25     db 'NUL.*', 0
