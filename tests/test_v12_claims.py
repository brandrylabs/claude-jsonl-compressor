"""Anonymous clause, quantity and language checks through the v12 draft protocol."""
from pathlib import Path
import json
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import _fixtures as fx
from test_v12_workflow import command
from v12_memory import END, validate_draft


def verify(source, claim, quote=None, topic=None):
    heading = "## Current State\n" + (f"### {topic}\n" if topic else "")
    draft = f"{heading}- {claim} [E1]\n> E1 | {quote or source}\n{END}"
    return validate_draft(draft, {"E1": source}, {})


class TestV12Claims(unittest.TestCase):
    def test_currencies_counts_and_roles(self):
        for source, claim in [
                ("布展费用锁定为 34 万元。", "布展费用锁定为 34 亿元。"),
                ("结算上限为 64 欧元。", "结算上限为 64 美元。"),
                ("初估需要约 16 份。", "初估需要 16 份。"),
                ("Budget USD 48.", "Budget EUR 48."),
                ("成本为 21 万美元。", "成本为 21 万欧元。"),
                ("温室原定 18 天，现定 26 天。", "温室原定 26 天，现定 18 天。"),
                ("纸本限定 14 页，电子本限定 22 页。", "纸本限定 22 页，电子本限定 14 页。"),
                ("Previously 11 days, now 9 days.", "Previously 9 days, now 11 days.")]:
            with self.subTest(claim=claim), self.assertRaises(ValueError):
                verify(source, claim)
        for source, claim in [
                ("总额为 172800 元。", "总额为 172,800 元。"),
                ("请看表 7（B 组）的记录。", "请看表 7 B 组的记录。"),
                ("Previously 11 days, now 9 days.", "Now 9 days, previously 11 days.")]:
            with self.subTest(claim=claim):
                self.assertIn(claim, verify(source, claim)["body"])

    def test_boundaries_subjects_and_qualifications(self):
        for source, claim, quote in [
                ("未来仪器采购尚未核准。", "未来仪器采购已经核准。", None),
                ("样柜尚未封存，留样箱已经封存。", "样柜已经封存，留样箱尚未封存。", None),
                ("样柜并未封存，留样箱已封存。", "样柜已封存。", "样柜"),
                ("若取得书面批准，仓库方可开放。", "仓库可以开放。", "仓库方可开放"),
                ("若取得书面批准，仓库方可开放。", "若取得口头批准，仓库方可开放。", None),
                ("仓库仅限白天开放。", "仓库开放。", "仓库"),
                ("仓库仅限白天开放。", "仓库仅限夜间开放。", None),
                ("甲队获准查阅档案，乙队获准复制档案。", "甲队获准复制档案，乙队获准查阅档案。", None),
                ("The box is closed. The second box is not closed.", "The box is closed.", "closed.")]:
            with self.subTest(claim=claim), self.assertRaises(ValueError):
                verify(source, claim, quote)
        verify("团队排定下一季的巡检计划。", "团队排定未来一季的巡检计划。")
        verify("样柜已经封存，留样箱尚未封存。", "样柜已经封存。", "样柜已经封存")

    def test_source_language_and_unsupported_translation(self):
        for source, claim in [
                ("온실 점검은 매주 시행한다.", "온실 점검은 매주 진행한다."),
                ("Архив хранит копию плана.", "Копия плана хранится в архиве."),
                ("تم اعتماد خطة الأرشيف.", "خطة الأرشيف معتمدة.")]:
            with self.subTest(claim=claim):
                checks = verify(source, claim)["audit"]["claims"][0]["checks"]
                self.assertEqual(checks["wording"], "lexical-overlap")
                self.assertEqual(verify(source, source)["audit"]["claims"][0]["checks"]["wording"], "source-literal")
        for source, claim in [("Склад остаётся закрытым.", "仓库明天开放。"),
                              ("у KioskApp нет разрешения на экспорт", "给 KioskApp 开放导出权限。"),
                              ("只准在馆内使用。", "Release it publicly."),
                              ("Keep the warehouse closed.", "Keep the warehouse closed 私下开放。"),
                              ("Keep the door closed.", "Keep the door closed. 仓库对外开放。")]:
            with self.subTest(claim=claim), self.assertRaises(ValueError):
                verify(source, claim)

    def test_supported_topic_and_credential_filter(self):
        source = "The slate tile stays indoors."
        self.assertIn("### slate tile", verify(source, source, topic="slate tile")["body"])
        with self.assertRaises(ValueError):
            verify(source, source, topic="private sale")
        with self.assertRaises(ValueError):
            verify("The plan is not approved.", "The plan is not approved.", topic="approved")
        with self.assertRaises(ValueError):
            verify("The plan is not approved.", "The plan is not approved.", quote="approved", topic="approved")
        with self.assertRaises(ValueError):
            verify("password: " + "example", "password: " + "example")

    def test_semantic_rejection_retry_and_finish(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            transcript = fx.TranscriptBuilder("77777777-1111-4333-8333-777777777777")
            evidence = ["温室原定 18 天，现定 26 天。", "The shutters stay closed.",
                        "检查门栓。", "门栓已经确认。"]
            for i in range(12):
                evidence.extend([f"Inspect cupboard {i}.", f"Cupboard {i} is closed."])
            for index in range(0, len(evidence), 2):
                transcript.user(evidence[index])
                transcript.assistant_text(evidence[index + 1])
            transcript.user("Retain the recent section.")
            transcript.assistant_text("The recent section is retained.")
            transcript.last_prompt()
            source = fx.write_jsonl(base / "session.jsonl", transcript.records)
            run = base / "run"
            command("prepare", "--input", source, "--run", run, "--min-recent-records", 2,
                    "--target-ratio", 0.05)
            job = json.loads((run / "run-plan.json").read_bytes())["jobs"][0]
            sources = json.loads((run / job["support"]).read_bytes())["sources"]
            lines = ["## 当前状态", "### 温室"]
            for key, text in sources.items():
                fact = next(f for f in evidence if f in text)
                lines.append(f"- {fact} [{key}]")
                lines.append(f"> {key} | {fact}")
            draft = "\n".join([*lines, END])
            path = base / "draft.md"
            path.write_text(draft.replace("原定 18 天，现定 26 天", "原定 26 天，现定 18 天", 1), encoding="utf-8")
            with self.assertRaises(ValueError):
                command("submit", "--run", run, "--task", job["id"], "--draft", path)
            path.write_text(draft, encoding="utf-8")
            command("submit", "--run", run, "--task", job["id"], "--draft", path)
            self.assertTrue(command("finish", "--run", run)["structure"])
            rows = [json.loads(line) for line in (run / "candidate.jsonl").read_bytes().splitlines()]
            body = next(row["message"]["content"] for row in rows if row.get("isCompactSummary"))
            self.assertIn("### 温室", body)
            self.assertIn(evidence[0], body)
