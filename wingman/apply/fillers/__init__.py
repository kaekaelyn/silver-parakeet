"""Per-ATS form fillers. Each module exposes fill(page, packet) -> FillReport."""

from wingman.apply.fillers import ashby, greenhouse, lever, workable

FILLERS = {
    greenhouse.ATS: greenhouse,
    lever.ATS: lever,
    ashby.ATS: ashby,
    workable.ATS: workable,
}
