"""Per-ATS form fillers. Each module exposes fill(page, packet) -> FillReport."""

from wingman.apply.fillers import greenhouse, lever

FILLERS = {
    greenhouse.ATS: greenhouse,
    lever.ATS: lever,
}
