; WPRST.COM (test_kernel t_wpfail): INT 21h 0Dh (disk reset)
org 100h
 mov ah, 0Dh
 int 21h
 ret
