<script lang="ts">
  let { open = false, onclose }: { open?: boolean; onclose: () => void } = $props();

  const KEYS: [string, string][] = [
    ["1 – 6", "코어 상태: 대기 / 듣기 / 생각 / 말하기 / 알림 / 오프라인"],
    ["스페이스 (길게)", "말하기 — 모의 모드에서는 가짜 음성으로 시연"],
    ["T", "텍스트로 명령 입력"],
    ["R", "리마인더 알림"],
    ["E", "일정 예고 알림"],
    ["D / Shift+D", "졸음 경고 1단계 / 2단계"],
    ["Esc", "알림 닫기"],
    ["M", "새 메시지 도착"],
    ["G", "Gmail 인증 만료 토글"],
    ["C", "캘린더 오프라인 토글"],
    ["F", "집중 모드 시작/종료"],
    ["N / P", "다음 곡 / 재생·일시정지"],
    ["?", "이 도움말"],
  ];
</script>

{#if open}
  <div class="scrim" role="presentation" onclick={onclose}>
    <div class="sheet" role="dialog" aria-label="개발자 단축키">
      <h3>개발자 단축키</h3>
      <dl>
        {#each KEYS as [k, v]}
          <dt class="num">{k}</dt>
          <dd>{v}</dd>
        {/each}
      </dl>
    </div>
  </div>
{/if}

<style>
  .scrim {
    position: fixed;
    inset: 0;
    z-index: 10;
    display: grid;
    place-items: center;
    background: rgba(3, 10, 18, 0.78);
  }
  .sheet {
    min-width: 460px;
    padding: 22px 28px;
    background: #07131e;
    border: 1px solid var(--tide-line);
  }
  h3 {
    margin: 0 0 14px;
    font-size: 15px;
    color: var(--arc);
  }
  dl {
    display: grid;
    grid-template-columns: auto 1fr;
    gap: 7px 20px;
    margin: 0;
  }
  dt {
    color: var(--frost);
  }
  dd {
    margin: 0;
    color: var(--frost-2);
  }
</style>
