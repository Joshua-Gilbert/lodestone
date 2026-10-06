; Extra 8x16 glyphs for CLAUDE, codes 80h-A0h, appended after FONT.INC
; (which ends with 7Fh).  Drawn to match Terminus Bold weight.
; 80h bullet
        db 000h,000h,000h,000h,000h,03Ch,07Eh,07Eh,07Eh,07Eh,03Ch,000h,000h,000h,000h,000h
; 81h result corner (like U+23BF)
        db 030h,030h,030h,030h,030h,030h,030h,030h,03Fh,03Fh,000h,000h,000h,000h,000h,000h
; 82h ellipsis
        db 000h,000h,000h,000h,000h,000h,000h,000h,000h,000h,0DBh,0DBh,000h,000h,000h,000h
; 83h right arrow
        db 000h,000h,000h,000h,010h,018h,01Ch,0FEh,0FEh,01Ch,018h,010h,000h,000h,000h,000h
; 84h check mark
        db 000h,000h,000h,000h,003h,007h,00Eh,0DCh,0F8h,070h,020h,000h,000h,000h,000h,000h
; 85h cross
        db 000h,000h,000h,000h,0C6h,0EEh,07Ch,038h,07Ch,0EEh,0C6h,000h,000h,000h,000h,000h
; 86h middle dot
        db 000h,000h,000h,000h,000h,000h,000h,018h,018h,000h,000h,000h,000h,000h,000h,000h
; 87h-8Ch spinner: small dot, plus, asterisk, star, big asterisk, heavy asterisk
        db 000h,000h,000h,000h,000h,000h,000h,018h,018h,000h,000h,000h,000h,000h,000h,000h
        db 000h,000h,000h,000h,000h,010h,010h,07Ch,010h,010h,000h,000h,000h,000h,000h,000h
        db 000h,000h,000h,000h,092h,054h,038h,0FEh,038h,054h,092h,000h,000h,000h,000h,000h
        db 000h,000h,000h,010h,038h,0FEh,07Ch,038h,07Ch,06Ch,0C6h,000h,000h,000h,000h,000h
        db 000h,000h,000h,010h,092h,054h,038h,0FEh,038h,054h,092h,010h,000h,000h,000h,000h
        db 000h,000h,000h,010h,0D6h,07Ch,0FEh,07Ch,0D6h,010h,000h,000h,000h,000h,000h,000h
; 8Dh horizontal rule
        db 000h,000h,000h,000h,000h,000h,000h,0FFh,0FFh,000h,000h,000h,000h,000h,000h,000h
; 8Eh vertical bar
        db 018h,018h,018h,018h,018h,018h,018h,018h,018h,018h,018h,018h,018h,018h,018h,018h
; 8Fh small right triangle
        db 000h,000h,000h,000h,000h,020h,030h,038h,03Ch,038h,030h,020h,000h,000h,000h,000h
; 90h degree
        db 000h,000h,038h,06Ch,06Ch,038h,000h,000h,000h,000h,000h,000h,000h,000h,000h,000h
; 91h micro
        db 000h,000h,000h,000h,000h,000h,066h,066h,066h,066h,066h,07Eh,060h,060h,0C0h,000h
; 92h ohm
        db 000h,000h,000h,038h,06Ch,0C6h,0C6h,0C6h,0C6h,06Ch,06Ch,0EEh,000h,000h,000h,000h
; 93h plus-minus
        db 000h,000h,000h,000h,018h,018h,07Eh,018h,018h,000h,07Eh,000h,000h,000h,000h,000h
; 94h times
        db 000h,000h,000h,000h,000h,000h,066h,03Ch,018h,03Ch,066h,000h,000h,000h,000h,000h
; 95h approximately
        db 000h,000h,000h,000h,000h,000h,076h,0DCh,000h,076h,0DCh,000h,000h,000h,000h,000h
; 96h less or equal
        db 000h,000h,000h,00Ch,018h,030h,060h,030h,018h,00Ch,000h,07Eh,000h,000h,000h,000h
; 97h greater or equal
        db 000h,000h,000h,030h,018h,00Ch,006h,00Ch,018h,030h,000h,07Eh,000h,000h,000h,000h
; 98h-A0h box drawing, lines on the same rows/columns as 8Dh and 8Eh
; 98h corner bottom-left (└)
        db 018h,018h,018h,018h,018h,018h,018h,01Fh,01Fh,000h,000h,000h,000h,000h,000h,000h
; 99h corner bottom-right (┘)
        db 018h,018h,018h,018h,018h,018h,018h,0F8h,0F8h,000h,000h,000h,000h,000h,000h,000h
; 9Ah corner top-left (┌)
        db 000h,000h,000h,000h,000h,000h,000h,01Fh,01Fh,018h,018h,018h,018h,018h,018h,018h
; 9Bh corner top-right (┐)
        db 000h,000h,000h,000h,000h,000h,000h,0F8h,0F8h,018h,018h,018h,018h,018h,018h,018h
; 9Ch tee right (├)
        db 018h,018h,018h,018h,018h,018h,018h,01Fh,01Fh,018h,018h,018h,018h,018h,018h,018h
; 9Dh tee left (┤)
        db 018h,018h,018h,018h,018h,018h,018h,0F8h,0F8h,018h,018h,018h,018h,018h,018h,018h
; 9Eh tee down (┬)
        db 000h,000h,000h,000h,000h,000h,000h,0FFh,0FFh,018h,018h,018h,018h,018h,018h,018h
; 9Fh tee up (┴)
        db 018h,018h,018h,018h,018h,018h,018h,0FFh,0FFh,000h,000h,000h,000h,000h,000h,000h
; A0h cross (┼)
        db 018h,018h,018h,018h,018h,018h,018h,0FFh,0FFh,018h,018h,018h,018h,018h,018h,018h
