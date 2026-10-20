"""The smallest useful plugin: one step. No core changes, no registration list to edit.

    factory plugins --plugin hello_plugin          # it shows up under `step`
    factory run my-workflow.yaml --plugin hello_plugin

(put examples/ on PYTHONPATH, or `cd examples`). In a workflow:

    - id: greet
      use: demo.hello
      with: { message: "hi" }
"""

from factory.core.context import Step, StepContext, StrictParams
from factory.core.models import StepResult
from factory.core.registry import register


class Params(StrictParams):  # unknown or misspelled keys in the YAML fail at load time
    message: str


@register("step", "demo.hello")
class Hello(Step):
    Params = Params
    needs = ()  # providers this step uses: "scm", "llm"... validated before anything runs

    def run(self, ctx: StepContext, p: Params) -> StepResult:
        # Outputs are what later steps read: ${steps.greet.outputs.text}
        return StepResult.ok(f"hello {ctx.job.name}", text=p.message)
