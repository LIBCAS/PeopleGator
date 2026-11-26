"""Shared fixture builders for processing regressions."""


def responses_result(status, output_text='', *, incomplete_details=None, usage=None):
    """Model a Responses result at the mocked SDK request boundary."""
    from openai.types.responses import Response, ResponseOutputMessage, ResponseOutputText

    text = ResponseOutputText.model_construct(type='output_text', text=output_text)
    message = ResponseOutputMessage.model_construct(type='message', content=[text])
    return Response.model_construct(
        status=status, output=[message], incomplete_details=incomplete_details, usage=usage)


def mention_fields(mention):
    """Capture source evidence and the original objects referenced by a mention."""
    return (
        mention.name, mention.text, mention.line, mention.span, mention.source_spans,
        mention.proposed_name, mention.description, mention.page_identity,
    )
