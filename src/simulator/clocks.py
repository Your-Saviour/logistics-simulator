"""One adapter process owns all HELICS handles and time requests."""
import json
import time

import helics as h


def advance_once(store, driver, target):
    if not store.prepare_request(target):
        return False
    grant = driver.request(target)
    if grant is None:
        return False
    store.grant(grant)
    return True


class HelicsClock:
    def __init__(self, config):
        self.config = json.loads(config)
        self.federate = h.helicsCreateCombinationFederateFromConfig(json.dumps(self.config))
        self.endpoint = h.helicsFederateGetEndpointByIndex(self.federate, 0)
        self.pending = False
        self.requested_at = None
        self.closed = False

    def initialize(self):
        h.helicsFederateEnterExecutingModeAsync(self.federate)
        self.requested_at = time.monotonic()

    def initialized(self):
        if not h.helicsFederateIsAsyncOperationCompleted(self.federate):
            return False
        h.helicsFederateEnterExecutingModeComplete(self.federate)
        self.requested_at = None
        return True

    def request(self, target):
        if self.pending:
            raise RuntimeError('A HELICS time request is already outstanding')
        h.helicsFederateRequestTimeAsync(self.federate, target)
        self.pending = True
        self.requested_at = time.monotonic()
        return None

    def poll(self):
        if self.pending and h.helicsFederateIsAsyncOperationCompleted(self.federate):
            value = h.helicsFederateRequestTimeComplete(self.federate)
            self.pending = False
            self.requested_at = None
            return float(value)
        return None

    def receive(self):
        messages = []
        while h.helicsEndpointHasMessage(self.endpoint):
            message = h.helicsEndpointGetMessage(self.endpoint)
            messages.append((message.source, json.loads(message.data)))
        return messages

    def values(self):
        return {h.helicsInputGetTarget(h.helicsFederateGetInputByIndex(self.federate, i)): h.helicsInputGetDouble(h.helicsFederateGetInputByIndex(self.federate, i))
                for i in range(h.helicsFederateGetInputCount(self.federate))}

    def publish_value(self, value):
        if h.helicsFederateGetPublicationCount(self.federate):
            h.helicsPublicationPublishDouble(h.helicsFederateGetPublicationByIndex(self.federate, 0), value)

    def send(self, envelope, endpoint):
        # Send now; the configured positive timeDelta/period delivers on the
        # next handoff boundary. SendToAt schedules the *send* at that future
        # time and would add another quantum before the receiver can consume.
        h.helicsEndpointSendBytesTo(self.endpoint, json.dumps(envelope), endpoint)

    def finalize(self):
        if not self.closed:
            h.helicsFederateDisconnect(self.federate)
            h.helicsFederateFree(self.federate)
            self.closed = True
