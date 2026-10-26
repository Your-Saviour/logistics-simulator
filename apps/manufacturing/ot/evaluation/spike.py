"""Bounded real OPC UA loopback spike; deliberately no production integration."""
import asyncio
import json
import platform
import resource
import statistics
import time
from asyncua import Server, Client, ua

ENDPOINT = 'opc.tcp://127.0.0.1:4840/simu77/'

async def server():
    instance = Server()
    await instance.init()
    instance.set_endpoint(ENDPOINT)
    namespace = await instance.register_namespace('urn:simu77:observation-only:v1')
    motor = await instance.nodes.objects.add_object(namespace, 'Motor')
    temperature = await motor.add_variable(ua.NodeId('temperature', namespace), 'Temperature', 25.0)
    # The client deliberately has no actuator and no writeable signal.
    return instance, temperature

async def main():
    started = time.monotonic()
    instance, temperature = await server()
    latencies = []
    async with instance:
        async with Client(ENDPOINT) as client:
            value = client.get_node(temperature.nodeid)
            stream_started = time.monotonic()
            for sample in range(100):
                expected = 35.0 + (sample % 10) / 10
                before = time.monotonic()
                await temperature.write_value(expected)
                assert await value.read_value() == expected
                latencies.append((time.monotonic() - before) * 1000)
                await asyncio.sleep(.1)
            stream_elapsed = time.monotonic() - stream_started
            degraded = ua.DataValue(ua.Variant(35.0, ua.VariantType.Double), StatusCode=ua.StatusCode(ua.StatusCodes.BadSensorFailure))
            await temperature.write_value(degraded)
            result = await value.read_data_value(raise_on_bad_status=False)
            assert result.StatusCode.is_bad()
            try:
                await value.write_value(999.0)
            except ua.UaStatusCodeError:
                pass
            else:
                raise AssertionError('Observer unexpectedly obtained write access')
        # A new session after disconnect must see the same node identity/quality.
        async with Client(ENDPOINT) as client:
            assert (await client.get_node(temperature.nodeid).read_data_value(raise_on_bad_status=False)).StatusCode.is_bad()
    # Recreate a server. Identity is reproducible; values are not claimed persistent.
    restarted, reset_temperature = await server()
    async with restarted:
        async with Client(ENDPOINT) as client:
            assert reset_temperature.nodeid == temperature.nodeid
            assert await client.get_node(temperature.nodeid).read_value() == 25.0
    print(json.dumps({'architecture':platform.machine(),'candidate':'asyncua==2.1.0','normal_samples':100,'devices':1,'target_rate_hz':10,'observed_rate_hz':100/stream_elapsed,'p95_observation_ms':sorted(latencies)[94],'mean_observation_ms':statistics.mean(latencies),'max_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,'cpu_seconds':resource.getrusage(resource.RUSAGE_SELF).ru_utime+resource.getrusage(resource.RUSAGE_SELF).ru_stime,'elapsed_seconds':time.monotonic()-started,'gates':{'normal':'pass','degraded_quality':'pass','observer_write_denied':'pass','disconnect_reconnect':'pass','restart_identity':'pass','restart_value_persistence':'fail: resets to model default','helics_step_control':'not implemented','manufacturing_path':'not adopted'}},indent=2))

asyncio.run(main())
