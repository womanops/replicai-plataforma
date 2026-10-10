# ReplicAI — Plataforma

SaaS de replicação e desdobramento de peças gráficas. O cliente envia a
arte-mãe, escolhe os formatos e baixa as peças re-diagramadas.

## Estrutura

```
motor/    o replica.py e o psd_io.py — o produto, intocado
api/      FastAPI: upload, fila, download
web/      front-end
infra/    Dockerfile e docker-compose
testes/   pytest
docs/     ROADMAP.md — o plano e as decisões
```

## Rodar local

```bash
cd infra && docker compose up
```

Abre em http://localhost:8000

## Status

Fase 0 (fundação) feita. Ver `docs/ROADMAP.md`.
