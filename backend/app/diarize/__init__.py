"""Sprekerdiarisatie: 'wie zegt wat'. Optioneel, standaard uit (DIARIZE_BACKEND=none).

Zelfde opzet als de STT-abstractie (backend/worker/stt): één interface, meerdere
implementaties, keuze via env. De zware backend (pyannote/torch) wordt lazy geïmporteerd,
zodat het importeren van dit pakket in de API/basis-worker geen torch binnenhaalt.
"""
