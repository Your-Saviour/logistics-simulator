(* Compatibility probe only. Production cell logic follows after this gate. *)
PROGRAM Handshake
VAR
    Enable AT %MW0 : UINT;
    GuardClosed AT %MW1 : UINT;
    PowerAvailable AT %MW2 : UINT;
    RequestSequence AT %MW3 : UINT;
    AcknowledgedSequence AT %QW0 : UINT;
    LogicalTransitions AT %QW1 : UINT;
    Conveyor AT %QW2 : UINT;
    Paused AT %QW3 : UINT;
END_VAR
IF RequestSequence <> AcknowledgedSequence THEN
    IF (Enable = 1) AND (GuardClosed = 1) AND (PowerAvailable = 1) THEN
        Conveyor := 1;
        Paused := 0;
        LogicalTransitions := LogicalTransitions + 1;
    ELSE
        Conveyor := 0;
        Paused := 1;
    END_IF;
    AcknowledgedSequence := RequestSequence;
END_IF;
END_PROGRAM

CONFIGURATION Config0
RESOURCE Res0 ON PLC
    TASK MainTask(INTERVAL := T#100ms, PRIORITY := 0);
    PROGRAM Cell WITH MainTask : Handshake;
END_RESOURCE
END_CONFIGURATION
