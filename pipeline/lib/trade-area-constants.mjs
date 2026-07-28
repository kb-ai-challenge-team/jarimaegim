/**
 * 서울시 우리마을가게 상권분석서비스 연동 상수.
 *
 * 시연용 매물에는 좌표·면적·임대조건만 있어 업종 적합성을 판정할 근거가 없었다.
 * 이 파일이 참조하는 네 데이터셋이 그 근거를 공급한다. 모두 서울 열린데이터광장의
 * 실측 공개 데이터이며, 여기서 파생되는 값 중 가정은 하나도 없다.
 */

/**
 * 수집 기준 분기. 2026-07-28 확인 결과 네 데이터셋 모두 20261이 최신이고
 * 20262는 아직 비어 있다. 갱신 주기가 분기이므로 새 분기가 열리면 이 값만 올린다.
 */
export const TRADE_AREA_QUARTER = "20261";

/** 열린데이터광장 OpenAPI 는 한 요청당 1000행이 상한이다. */
export const OPEN_API_PAGE = 1000;

/** 연속 호출 사이 간격. 공개 API에 부담을 주지 않기 위한 값이다. */
export const OPEN_API_RATE_LIMIT_MS = 120;

/**
 * 데이터셋별 수집 필드 화이트리스트.
 *
 * 매출 데이터셋은 요일별·시간대별·성별·연령대별로 50개가 넘는 컬럼을 준다. 지금
 * 판정에 쓰지 않는 컬럼까지 디스크에 남기면 나중에 어느 값이 실제로 근거로 쓰였는지
 * 알 수 없게 되므로, 쓰는 것만 받는다.
 */
export const TRADE_AREA_DATASETS = {
  geometry: {
    dataset: "TbgisTrdarRelm",
    quarterly: false,
    fields: ["TRDAR_CD", "TRDAR_CD_NM", "TRDAR_SE_CD_NM", "SIGNGU_CD_NM", "ADSTRD_CD", "ADSTRD_CD_NM", "RELM_AR"],
  },
  stores: {
    dataset: "VwsmTrdarStorQq",
    quarterly: true,
    // 개업률·폐업률(OPBIZ_RT·CLSBIZ_RT)은 상권 하나에 대한 백분율이다. 크기가 다른 상권들의
    // 백분율을 평균하면 점포 3개짜리 상권이 점포 300개짜리 상권과 같은 무게를 갖는다.
    // 그래서 비율이 아니라 원자료인 개업·폐업 점포 수를 함께 받아, 행정동 집계는
    // 합계끼리 나눠서 다시 구한다.
    fields: ["STDR_YYQU_CD", "TRDAR_CD", "SVC_INDUTY_CD", "SVC_INDUTY_CD_NM", "STOR_CO", "SIMILR_INDUTY_STOR_CO", "FRC_STOR_CO", "OPBIZ_STOR_CO", "CLSBIZ_STOR_CO"],
  },
  sales: {
    dataset: "VwsmTrdarSelngQq",
    quarterly: true,
    fields: ["STDR_YYQU_CD", "TRDAR_CD", "SVC_INDUTY_CD", "THSMON_SELNG_AMT", "THSMON_SELNG_CO"],
  },
  footfall: {
    dataset: "VwsmTrdarFlpopQq",
    quarterly: true,
    fields: ["STDR_YYQU_CD", "TRDAR_CD", "TOT_FLPOP_CO"],
  },
};

/**
 * 자치구·행정동이 이 서비스의 조인 키다.
 *
 * 상권영역 데이터셋은 중심좌표를 EPSG:5181 계열 TM 으로 주고, 매물 좌표는 WGS84 다.
 * 좌표계를 변환해 최근접 상권을 붙이면 폴리곤 없이 중심점 거리로만 판정하게 되어
 * 실제보다 정밀해 보이는 값이 나온다. 대신 상권영역이 함께 주는 행정동명으로 조인하고,
 * 한 행정동 안의 상권들을 집계한다. 집계 단위를 provenance 에 그대로 밝힌다.
 */
export const TRADE_AREA_SPATIAL_UNIT = "행정동 내 상권 집계";

/**
 * 행정동×업종을 싣기 위한 최소 점포 수.
 *
 * 얇은 표본을 걸러내는 기준은 상권 수가 아니라 점포 수다. 상권 하나뿐인 행정동이라도
 * 그 안에 커피전문점이 40곳이면 폐업률은 충분히 안정적이고, 반대로 상권이 셋이어도
 * 점포가 둘뿐이면 한 곳만 닫아도 폐업률이 50%로 튄다. 비율이 요동치는 것은 분모가
 * 작을 때이므로 분모에 건다.
 */
export const MIN_INDUSTRY_STORES = 5;
