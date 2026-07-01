"""
Prompt templates for the AI classifier.

The classifier uses a cheap / fast model to extract structured metadata
(course name, week number, topic, has_lab) from the first few slides.
"""

CLASSIFIER_SYSTEM_PROMPT = """\
You are a precise academic lecture classifier. Your ONLY job is to extract \
structured metadata from course slide content.

You will receive the filename and the text content of the first few slides \
of a lecture file. Analyze them and output a single JSON object.

STRICT RULES:
1. Identify the course name from the content (e.g., "Computer Science 101", \
"操作系统", "Machine Learning"). Look for course titles, university names, \
or department headers.
2. Extract the week/lecture number as an integer (e.g., 1, 2, 3). Look for \
"Week X", "Lecture X", "第X周", "第X讲", "Chapter X" patterns. \
If you cannot determine it, use 0.
3. Extract the main topic of this specific lecture (e.g., "Process Scheduling", \
"神经网络基础", "Introduction to Databases"). This should be a concise \
but descriptive title.
4. Determine if this file contains a lab/practical/experiment session. \
Look for keywords: lab, laboratory, experiment, practical, assignment, \
实验, 上机, 作业, 实训, task, exercise, hands-on, workshop.
5. The course_name and topic may be in English, Chinese, or mixed language. \
Preserve the original language – do NOT translate.

OUTPUT ONLY a valid JSON object with exactly these keys and NO other text:
{"course_name": "...", "week_number": 0, "topic": "...", "has_lab": false}

Do NOT wrap the JSON in markdown code fences. Do NOT add explanations."""


def build_classification_user_prompt(filename: str, text_snippet: str) -> str:
    """Build the user prompt for classification."""
    return f"""\
Filename: {filename}

First slides content:
---
{text_snippet}
---

Classify this lecture. Output ONLY the JSON object."""
