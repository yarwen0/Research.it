"""Application services.

The pipeline logic lives here, separated from how its progress reaches a
client. Routes in `api/` translate the events these emit into SSE; a queued
worker could persist them instead, without either side changing.
"""
