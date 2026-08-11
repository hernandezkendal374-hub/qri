from types import SimpleNamespace

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.db.session import build_engine
from app.funnel.runner import create_funnel_run, execute_funnel
from app.models import PipelineRun, PipelineStageRun


def test_daily_funnel_tracks_stages_and_prevents_concurrent_runs(monkeypatch) -> None:
    engine = build_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)

    run, created = create_funnel_run(factory)
    same_run, second_created = create_funnel_run(factory)
    assert created is True
    assert second_created is False
    assert same_run.run_id == run.run_id

    monkeypatch.setattr(
        "app.funnel.runner.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="ok", stderr=""),
    )
    execute_funnel(run.run_id, factory, python_executable="python")

    with factory() as session:
        completed = session.scalar(select(PipelineRun).where(PipelineRun.run_id == run.run_id))
        stages = list(
            session.scalars(
                select(PipelineStageRun)
                .where(PipelineStageRun.run_id == run.run_id)
                .order_by(PipelineStageRun.id)
            )
        )
        assert completed.status == "COMPLETE"
        assert completed.current_stage is None
        assert completed.error_count == 0
        assert len(stages) == 6
        assert all(stage.status == "SUCCESS" for stage in stages)
        assert all(stage.attempt_count == 1 for stage in stages)


def test_interrupted_funnel_resumes_without_repeating_completed_stages(monkeypatch) -> None:
    engine = build_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
    run, _ = create_funnel_run(factory)

    with factory() as session:
        completed = list(
            session.scalars(
                select(PipelineStageRun)
                .where(PipelineStageRun.run_id == run.run_id)
                .order_by(PipelineStageRun.id)
            )
        )[:2]
        for stage in completed:
            stage.status = "SUCCESS"
            stage.attempt_count = 1
            stage.metrics_json = {"created": 7}
        session.commit()

    calls = []

    def successful_stage(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr("app.funnel.runner.subprocess.run", successful_stage)
    execute_funnel(run.run_id, factory, python_executable="python")

    with factory() as session:
        stages = list(
            session.scalars(
                select(PipelineStageRun)
                .where(PipelineStageRun.run_id == run.run_id)
                .order_by(PipelineStageRun.id)
            )
        )
        assert len(calls) == 4
        assert [stage.attempt_count for stage in stages] == [1, 1, 1, 1, 1, 1]
        assert all(stage.status == "SUCCESS" for stage in stages)
