q_set   db 'SET?',10,0
meters  db 'DM5120DM5010DC5009',0
l_id    db 'ID?       $'
l_idn   db '*IDN?     $'
l_set   db 'SET?      $'
l_read  db 'reading   $'
l_spoll db 'ser.poll  $'
s_thdr  db 13,10,'Read-only test set (times per transaction, ms):',13,10,'$'
s_dhdr  db 13,10,'addr $'
s_2sp   db '  $'
s_noid2 db '(no ID reply - serial poll only)',13,10,'$'
s_ind   db '    $'
s_failed db '  FAILED$'
s_avg   db '  avg$'
s_min   db '  min$'
s_max   db '  max$'
s_ms    db ' ms$'
s_bytes db ' B$'
s_st    db '  status $'
s_then  db '  then failed$'
s_show  db '        "$'
s_show2 db '"',13,10,'$'
s_warn  db '    ** status after tests $'
s_warn2 db 'h (before $'
s_warn3 db 'h): error bit set - check the instrument display',13,10,'$'
s_sum1  db 13,10,'Summary: $'
s_sum2  db ' devices, $'
s_sum3  db ' transactions OK, $'
s_sum4  db ' failed',13,10,'Bus time $'
s_sum5  db ' ms, total run $'
s_sum6  db ' ms, chip recoveries $'
s_sum7  db ', warnings $'
prof    db 0
st_pre  db 0
t_show  db 0
t_st    db 0
pitset  db 0
t_si    dw 0
t_reps  dw 0
t_lbl   dw 0
t_ok    dw 0
rxcnt   dw 0
ntrans  dw 0
nfail   dw 0
nwarn   dw 0
t0      dd 0
t_sum   dd 0
t_min   dd 0
t_max   dd 0
t_bus   dd 0
tall    dd 0
s_ferr  db ' (err $'
s_fafter db ' after$'
s_fms   db ' ms)$'
lasterr dw 0
t_fail  dd 0
