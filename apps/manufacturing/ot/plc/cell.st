(* SIMU-54 batch carrier. Only a new request sequence evaluates a logical step. *)
PROGRAM AssemblyCell
VAR
    Enable AT %MW0 : UINT;
    GuardClosed AT %MW1 : UINT;
    PowerAvailable AT %MW2 : UINT;
    RequestSequence AT %MW3 : UINT;
    Positioned AT %MW4 : UINT;
    Clamped AT %MW5 : UINT;
    Processed AT %MW6 : UINT;
    Exited AT %MW7 : UINT;
    Healthy AT %MW8 : UINT;
    BatchNumber AT %MW9 : UINT;
    TargetGood AT %MW10 : UINT;
    TargetScrap AT %MW11 : UINT;
    ResetFault AT %MW12 : UINT;
    Active AT %MW13 : UINT;
    Cookie0 AT %MW14 : UINT;
    Cookie1 AT %MW15 : UINT;
    Cookie2 AT %MW16 : UINT;
    Cookie3 AT %MW17 : UINT;
    ResetCell AT %MW18 : UINT;
    AcknowledgedSequence AT %QW0 : UINT;
    Conveyor AT %QW1 : UINT;
    Clamp AT %QW2 : UINT;
    Cycle AT %QW3 : UINT;
    Fault AT %QW4 : UINT;
    Good AT %QW5 : UINT;
    Scrap AT %QW6 : UINT;
    CurrentBatch AT %QW7 : UINT;
    Echo0 AT %QW8 : UINT;
    Echo1 AT %QW9 : UINT;
    Echo2 AT %QW10 : UINT;
    Echo3 AT %QW11 : UINT;
    Counted : BOOL := FALSE;
END_VAR
IF RequestSequence <> AcknowledgedSequence THEN
    Conveyor := 0;
    Clamp := 0;
    Cycle := 0;
    IF ResetCell = 1 THEN
        Fault := 0;
        Good := 0;
        Scrap := 0;
        CurrentBatch := 0;
        Counted := FALSE;
    ELSE
        IF BatchNumber <> CurrentBatch THEN
            CurrentBatch := BatchNumber;
            Good := 0;
            Scrap := 0;
            Counted := FALSE;
        END_IF;
        IF (GuardClosed <> 1) OR (PowerAvailable <> 1) OR (Healthy <> 1) THEN
            Fault := 1;
        ELSIF ResetFault = 1 THEN
            Fault := 0;
        END_IF;
        IF (Exited = 1) AND NOT Counted AND (BatchNumber <> 0) THEN
            Good := TargetGood;
            Scrap := TargetScrap;
            Counted := TRUE;
        END_IF;
        IF (Enable = 1) AND (Fault = 0) AND (Active = 1) THEN
            IF (Positioned = 0) OR ((Processed = 1) AND (Clamped = 0)) THEN
                Conveyor := 1;
            ELSIF Processed = 0 THEN
                Clamp := 1;
                IF Clamped = 1 THEN
                    Cycle := 1;
                END_IF;
            END_IF;
        END_IF;
    END_IF;
    Echo0 := Cookie0;
    Echo1 := Cookie1;
    Echo2 := Cookie2;
    Echo3 := Cookie3;
    AcknowledgedSequence := RequestSequence;
END_IF;
END_PROGRAM

CONFIGURATION Config0
RESOURCE Res0 ON PLC
    TASK MainTask(INTERVAL := T#100ms, PRIORITY := 0);
    PROGRAM Cell WITH MainTask : AssemblyCell;
END_RESOURCE
END_CONFIGURATION
