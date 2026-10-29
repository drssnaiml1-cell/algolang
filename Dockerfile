# AlgoLang in a container: the same result on any machine.
#   docker run --rm -v "$PWD:/work" ghcr.io/drssnaiml1-cell/algolang run pack:insurance.claims_triage --arg "claim=bumper damage"
#   docker run --rm -p 8765:8765 -v "$PWD:/work" ghcr.io/drssnaiml1-cell/algolang studio --host 0.0.0.0 --no-browser
#   docker run --rm -e ANTHROPIC_API_KEY -v "$PWD:/work" ghcr.io/drssnaiml1-cell/algolang run my.algo --live
FROM python:3.12-slim AS build
WORKDIR /src
COPY . .
RUN pip install --no-cache-dir build && python -m build --wheel --outdir /dist

FROM python:3.12-slim
LABEL org.opencontainers.image.title="AlgoLang" \
      org.opencontainers.image.description="Agent-native programming language for governed multi-agent AI" \
      org.opencontainers.image.source="https://github.com/drssnaiml1-cell/algolang" \
      org.opencontainers.image.licenses="Apache-2.0"
COPY --from=build /dist/*.whl /tmp/
RUN pip install --no-cache-dir "$(ls /tmp/*.whl)[live]" && rm /tmp/*.whl && useradd -m algo
ENV PYTHONIOENCODING=utf-8
USER algo
WORKDIR /work
EXPOSE 8765
ENTRYPOINT ["algo"]
CMD ["doctor"]
