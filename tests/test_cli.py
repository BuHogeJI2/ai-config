import io

from ai_config.cli import main
from tests.helpers import FakeWorldTestCase


class DoctorCommandTest(FakeWorldTestCase):
    def run_doctor(self):
        out = io.StringIO()
        code = main(["doctor"], environ={"HOME": str(self.home)}, repo_root=self.repo, out=out)
        return code, out.getvalue()

    def test_clean_run_exits_zero(self):
        self.assertEqual(self.run_doctor(), (0, "0 error(s), 0 warning(s)\n"))

    def test_errors_exit_one_and_are_listed_first(self):
        self.add_skill(self.env.claude_skills, "plan")
        self.add_skill(self.repo / "claude/skills", "orphan")
        code, output = self.run_doctor()
        self.assertEqual(code, 1)
        self.assertEqual(
            output.splitlines(),
            [
                "error    claude/skills/orphan: skill has no manifest entry",
                "info     unmanaged claude skill: ~/.claude/skills/plan",
                "1 error(s), 0 warning(s)",
            ],
        )
