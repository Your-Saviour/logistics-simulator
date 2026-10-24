#!/usr/bin/env python3
"""Print resource/health evidence without dumping container environments."""
import subprocess


def main():
    subprocess.run(['docker','info','--format','CPUs={{.NCPU}} Memory={{.MemTotal}}'])
    subprocess.run(['docker','stats','--no-stream','--format','{{.Name}} memory={{.MemUsage}} cpu={{.CPUPerc}} pids={{.PIDs}}'])
    ids=subprocess.check_output(['docker','compose','-f','deploy/generated/suite.json','ps','-a','-q'],text=True).split()
    for container in ids:
        result=subprocess.run(['docker','inspect','--format','{"name":{{json .Name}},"state":{{json .State}}}',container],text=True,capture_output=True)
        if result.returncode==0:
            print(result.stdout.strip(),flush=True)
    subprocess.run(['docker','compose','-f','deploy/generated/suite.json','logs','--tail','120'])


if __name__=='__main__':
    main()
