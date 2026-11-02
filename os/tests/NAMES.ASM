; NAMES.COM (test_kernel t_names): what INT 21h answers for names with a
; second dot or a bad character, for device names and for CREATE over
; hidden and system files.  Each line: fn, the name(s), ok or the error.
; test_kernel holds the answers GRiD MS-DOS 3.30 gives
%include "PROBE.INC"
; X15: a second dot (A.TXT, B.TXT, A.B\X.TXT and E.F empty are there)
tests   dw 3D00h, a_x, 0, 0
        dw 3C00h, n_ab, 0, 0
        dw 3900h, d_ef, 0, 0
        dw 4E00h, a_x, 0, 0
        dw 4E00h, w_x, 0, 0
        dw 4300h, a_x, 0, 0
        dw 3B00h, ab_c, 0, 0
        dw 3B00h, root, 0, 0
        dw 3D00h, abc_x, 0, 0
        dw 3D00h, a_dot, 0, 0
        dw 3D00h, a_dd, 0, 0
        dw 5600h, a_txt, c_de, 0
        dw 5600h, a_x, z_txt, 0
        dw 4100h, b_x, 0, 0
        dw 3A00h, ef_g, 0, 0
; X16: devices, hidden, system and read-only files
        dw 3900h, s_con, 0, 0
        dw 3900h, s_nul, 0, 0
        dw 3D00h, hid, 0, 0
        dw 3C00h, hid, 0, 0
        dw 3C00h, sys, 0, 0
        dw 3C00h, ro, 0, 0
        dw 5B00h, hid, 0, 0
        dw 4100h, sys, 0, 0
        dw 4100h, hid, 0, 0
        dw 4100h, s_con, 0, 0
        dw 5600h, b_txt, s_con, 0
; more: bad characters, the hidden attribute asked for, devices
        dw 3D00h, s_bar, 0, 0
        dw 3C00h, s_bar, 0, 0
        dw 3900h, s_bar, 0, 0
        dw 3D00h, s_barx, 0, 0
        dw 4100h, s_bar, 0, 0
        dw 3C00h, hid2, 0, 2
        dw 4100h, ro, 0, 0
        dw 5B00h, s_con, 0, 0
        dw 3A00h, s_con, 0, 0
        dw 3B00h, s_con, 0, 0
        dw 3D00h, s_conx, 0, 0
        dw 3C00h, sys2, 0, 2
        dw 3C00h, hid3, 0, 6
        dw 3C00h, hs, 0, 2
        dw 3C00h, hs2, 0, 6
; devices only where the path is there; MS-DOS looks up RENAME's old name first
        dw 3900h, nos_con, 0, 0
        dw 3A00h, nos_con, 0, 0
        dw 4100h, nos_con, 0, 0
        dw 4100h, ab_con, 0, 0
        dw 3900h, ab_con, 0, 0
        dw 3A00h, ab_con, 0, 0
        dw 5600h, nos_txt, s_con, 0
        dw 5600h, ro, nos_con, 0
        dw 4100h, clk_txt, 0, 0
        dw 3900h, clk_s, 0, 0
        dw 3900h, clk, 0, 0
        dw 3A00h, clk, 0, 0
; EXEC answers as OPEN; CREATE NEW as CREATE
        dw 4B00h, ab_c, 0, 0
        dw 4B00h, a_x, 0, 0
        dw 4B00h, s_bar, 0, 0
        dw 5B00h, n_ab, 0, 0
        dw 5B00h, s_bar, 0, 0
        dw 0
a_x     db 'A.TXT.X', 0
w_x     db '*.TXT.X', 0
n_ab    db 'N.A.B', 0
d_ef    db 'D.E.F', 0
ab_c    db 'A.B.C', 0
root    db '\', 0
abc_x   db 'A.B.C\X.TXT', 0
a_dot   db 'A.TXT.', 0
a_dd    db 'A..TXT', 0
a_txt   db 'A.TXT', 0
c_de    db 'C.D.E', 0
z_txt   db 'Z.TXT', 0
b_x     db 'B.TXT.X', 0
b_txt   db 'B.TXT', 0
ef_g    db 'E.F.G', 0
s_con   db 'CON', 0
s_nul   db 'NUL', 0
hid     db 'HID.TXT', 0
sys     db 'SYS.TXT', 0
ro      db 'RO.TXT', 0
s_bar   db 'A|B', 0
s_barx  db 'A|B\X.TXT', 0
hid2    db 'HID2.TXT', 0
s_conx  db 'CON.TXT', 0
sys2    db 'SYS2.TXT', 0
hid3    db 'HID3.TXT', 0
hs      db 'HS.TXT', 0
hs2     db 'HS2.TXT', 0
nos_con db 'NOSUCH\CON', 0
ab_con  db 'A.B\CON', 0
nos_txt db 'NOSUCH.TXT', 0
clk_txt db 'CLOCK.TXT', 0
clk_s   db 'CLOCK$', 0
clk     db 'CLOCK', 0
