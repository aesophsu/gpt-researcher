import Image from "next/image";

interface SubQuestionsProps {
  metadata: string[];
  handleClickSuggestion: (value: string) => void;
  awaitingClarification?: boolean;
}

const SubQuestions: React.FC<SubQuestionsProps> = ({
  metadata,
  handleClickSuggestion,
  awaitingClarification = false,
}) => {
  return (
    <div className="container flex w-full items-start gap-3 pt-5 pb-2">
      <div className="flex w-fit items-center gap-4">
        <img
          src={"/img/thinking.svg"}
          alt="thinking"
          width={30}
          height={30}
          className="size-[24px]"
        />
      </div>
      <div className="grow text-white">
        <p className="pr-5 font-bold leading-[152%] text-white pb-[20px]">
          Pondering your question from several angles
        </p>
        {awaitingClarification && (
          <div className="inline-flex items-center rounded-full border border-amber-400/40 bg-amber-500/10 px-3 py-1 text-xs font-medium text-amber-200 mb-3">
            Waiting for your clarification to continue research
          </div>
        )}
        <div className="flex flex-row flex-wrap items-center gap-2.5 pb-[20px]">
          {metadata.map((item, subIndex) => (
            <div
              className="flex cursor-pointer items-center justify-center gap-[5px] rounded-full border border-solid border-[#C1C1C1] bg-[#EDEDEA] px-2.5 py-2"
              onClick={() => handleClickSuggestion(item)}
              key={`${item}-${subIndex}`}
            >
              <span className="text-sm font-light leading-[normal] text-[#1B1B16]">
                {item}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};

export default SubQuestions;
