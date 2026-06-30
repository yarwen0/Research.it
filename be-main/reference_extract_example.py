import core
import config

ex = core.ReferenceParameterExtractorFallback(config.GEMINI_API_KEY)

res = ex.extract("H. Shi, Q. Jiang, K. Yang, X. Yin, H. Ni, and K. Wang, “Beyond the field-of-view: Enhancing scene visibility and perception with clip- recurrent transformer,” arXiv preprint arXiv:2211.11293, 2022. ")
print(res)