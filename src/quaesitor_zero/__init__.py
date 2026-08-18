"""quaesitor-zero — does your assistant say "I don't know" when it cannot know?

The free floor of the Quaesitor method. It measures one thing: whether a
data assistant declines the questions its data cannot answer, without
declining the ones it can.

It never connects to a model. The core has no LLM dependency at all, because a
tool asking to be trusted about model behaviour cannot itself be a model.
"""

__version__ = "0.1.0"
