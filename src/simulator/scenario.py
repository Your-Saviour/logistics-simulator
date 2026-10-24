"""Persisted scenario calendar. Simulation seconds are elapsed UTC seconds."""
from datetime import datetime, time, timedelta, timezone
import math
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from pydantic import BaseModel, ConfigDict, Field, model_validator


class Scenario(BaseModel):
    model_config = ConfigDict(extra='forbid')
    seed: int = Field(default=1,ge=0,le=2147483647)
    time_zone: str = 'Australia/Adelaide'
    start_at: datetime = datetime.fromisoformat('2026-01-05T08:00:00+10:30')
    business_open: time = time(8)
    business_close: time = time(17)
    business_weekdays: list[int] = Field(default_factory=lambda:[0,1,2,3,4])
    interval_seconds: int = Field(default=30,ge=1,le=86400)

    @model_validator(mode='after')
    def valid_calendar(self):
        try:
            ZoneInfo(self.time_zone)
        except ZoneInfoNotFoundError as exc:
            raise ValueError('Unknown scenario timezone') from exc
        if self.start_at.utcoffset() is None:
            raise ValueError('Scenario start_at needs an explicit UTC offset')
        if self.business_open >= self.business_close or self.business_open.tzinfo or self.business_close.tzinfo:
            raise ValueError('Business hours must be increasing local times within one day')
        if any(t.second or t.microsecond for t in (self.business_open,self.business_close)):
            raise ValueError('Business hours use whole local minutes')
        if not self.business_weekdays or len(set(self.business_weekdays))!=len(self.business_weekdays) or any(type(day) is not int or not 0<=day<=6 for day in self.business_weekdays):
            raise ValueError('Business weekdays must be unique integers from Monday=0 to Sunday=6')
        return self

    def instant(self, seconds):
        return datetime.fromtimestamp(self.start_at.timestamp()+seconds,ZoneInfo(self.time_zone))


def _openings(day, wall, zone):
    # At a DST gap choose the first valid local minute. Both occurrences of a
    # repeated opening are candidates; the caller selects the next future one.
    naive=datetime.combine(day,wall)
    for _ in range(181):
        candidates={}
        for fold in (0,1):
            candidate=naive.replace(tzinfo=zone,fold=fold)
            if datetime.fromtimestamp(candidate.timestamp(),zone).replace(tzinfo=None)==naive:
                candidates[candidate.timestamp()]=candidate
        if candidates:
            return [candidates[stamp] for stamp in sorted(candidates)]
        naive+=timedelta(minutes=1)
    raise ValueError('Business opening cannot be resolved in this timezone')


def next_business_due(scenario: Scenario, after_seconds: float, minimum_delay: float):
    if not math.isfinite(after_seconds) or not math.isfinite(minimum_delay) or after_seconds<0 or minimum_delay<=0:
        raise ValueError('A finite nonnegative time and positive delay are required')
    candidate=scenario.instant(after_seconds+minimum_delay)
    zone=ZoneInfo(scenario.time_zone)
    if candidate.weekday() in scenario.business_weekdays and scenario.business_open<=candidate.time()<scenario.business_close:
        return after_seconds+minimum_delay
    for offset in range(8):
        day=candidate.date()+timedelta(days=offset)
        if day.weekday() not in scenario.business_weekdays:
            continue
        for opening in _openings(day,scenario.business_open,zone):
            if opening.timestamp()>=candidate.timestamp() and opening.time()<scenario.business_close:
                return opening.timestamp()-scenario.start_at.timestamp()
    raise ValueError('No valid business opening in the next week')
