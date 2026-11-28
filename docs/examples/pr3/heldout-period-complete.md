# Historical exports

The service retains export data for six weeks after ingestion.

An operator chooses a date within the retained interval and receives its export.
For a valid date without records, the service returns an empty export.
A request outside the retained interval is rejected and reports the available interval.
