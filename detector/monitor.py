# Read logs
import json
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Generator, Optional

@dataclass
class logEvent:
    source_ip:str
    timestamp:datetime
    method:str
    path:str
    status:int
    response_size:int

# Parse log line into logEvent
def parse_log_line(line:str) -> Optional[logEvent]:
    line = line.strip()
    if not line:
        return None

    try:
        payload = json.loads(line)

        timeStamp = datetime.fromisoformat(payload['timestamp'].replace("Z", "+00:00"))
        return logEvent(
            source_ip = str(payload['source_ip']),
            timestamp = timeStamp,
            method = str(payload['method']),
            path = str(payload['path']),
            status = int(payload['status']),
            response_size = int(payload['response_size']),

        )
    except (ValueError, KeyError, TypeError, json.JSONDecodeError):
        # ignore invalid lines, daemon must keep running
        return None


def tail_log_file(path: str, poll_interval_seconds: float = 0.2) -> Generator[logEvent, None, None]:
    with open(path, "r", encoding="utf-8") as f:
        # should start at the end of the file and process only new events
        f.seek(0, 2)

        while True:
            line = f.readline()
            if not line:
                time.sleep(poll_interval_seconds)
                continue

            event = parse_log_line(line)
            if event is not None:
                yield event

