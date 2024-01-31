'''
Run through all folds of Fridriksson
S2S model jointly optimized for both ASR and paraphasia detection
Model is first trained on proto dataset and PD is on 'pn'
'''
import os
import shutil
import subprocess
import time
import datetime
import pandas as pd
from sklearn.metrics import f1_score, recall_score, precision_score
from collections import Counter
import pickle
from scipy import stats
import re
import socket
from tqdm import tqdm

def find_free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('', 0))
        return s.getsockname()[1]



TOT_EPOCHS=120

def train_log_check(train_log_file, last_epoch):
    with open(train_log_file, 'r') as file:
        last_line = file.readlines()[-1].strip()

        if int(last_line.split()[2]) == last_epoch:
            return True
        else:
            print(f"Error, last line epoch = {last_line.split()[2]}")
            return False
      
def compute_maj_class(fold,para_type):
    # compute majority class for naive baseline
    data = f"/home/mkperez/speechbrain/AphasiaBank/data/Fridriksson_para/Fold_{fold}/train_{para_type}.csv"
    df = pd.read_csv(data)
    PARA_DICT = {'P':1, 'C':0}
    utt_tr = []
    word_tr = []
    for utt in df['aug_para']:
        utt_arr = []
        for p in utt.split():
            utt_arr.append(PARA_DICT[p.split("/")[-1]])
        utt_tr.append(max(utt_arr))
    
    utt_counter = Counter(utt_tr)
    maj_class_utt = utt_counter.most_common()[0][0]
    return maj_class_utt

## TD for multi
def TD_helper(true_labels, predicted_labels):
    print(f"true_labels: {true_labels}")
    print(f"predicted_labels: {predicted_labels}")
    TTC = 0
    for i in range(len(true_labels)):
        # for paraphasia label
        if true_labels[i] != 'c':
            min_distance_for_label = max(i-0,len(true_labels)-i)
            for j in range(len(predicted_labels)):
                if true_labels[i] == predicted_labels[j]:
                    # check for min distance
                    if abs(i - j) < min_distance_for_label:
                        min_distance_for_label = abs(i - j)

            TTC += min_distance_for_label


    CTT = 0
    for j in range(len(predicted_labels)):
        if predicted_labels[j] != 'c':
            min_distance_for_label = max(j-0,len(predicted_labels)-j)
            for i in range(len(true_labels)):
                if true_labels[i] == predicted_labels[j]:
                    # check for min distance
                    if abs(i - j) < min_distance_for_label:
                        min_distance_for_label = abs(i - j)

            CTT += min_distance_for_label
    print(f"TD: {TTC + CTT}\n")
    return TTC + CTT

def compute_temporal_distance(true_labels, predicted_labels):
    # Return list of TDs for each utterance
    TD_per_utt = []
    for true_label, pred_label in zip(true_labels, predicted_labels):
        TD_utt = TD_helper(true_label, pred_label)
        TD_per_utt.append(TD_utt)

        print(f"true_label: {true_label}")
        print(f"pred_label: {pred_label}")
        print(f"TD_utt: {TD_utt}\n")
        # print(f"TD_utt: {TD_utt}")
        # if TD_utt > 200:
        #     print(f"true_label: {true_label}")
        #     print(f"pred_label: {pred_label}")
        #     exit()
    

    return sum(TD_per_utt) / len(TD_per_utt)
    


## TTR
def compute_time_tolerant_scores(true_labels, predicted_labels, n=0):
    # Input: true_labels and predicted labels is a list of lists of labels
    # Output: number of TP, FN, FP
    assert len(true_labels) == len(predicted_labels), "Length of true_labels and predicted_labels must be the same"

    TP = 0  # True Positives
    FN = 0  # False Negatives
    FP = 0  # False Positives

    
    for utt_true, utt_pred in zip(true_labels, predicted_labels):
        for i, (true_label, predicted_label) in enumerate(zip(utt_true, utt_pred)):
            neighborhood = utt_pred[max(i-n, 0):min(i+n+1, len(utt_pred))]

            if true_label != 'c' and true_label != '<eps>':
                if any(label == true_label for label in neighborhood):
                    TP += 1
                else:
                    FN += 1

            elif any(label in ['p','n','s']  for label in neighborhood):
                FP += 1

    # Calculating precision and recall
    precision = TP / (TP + FP) if (TP + FP) > 0 else 0
    recall = TP / (TP + FN) if (TP + FN) > 0 else 0

    # Calculating F1-score
    f1_score = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0
    return f1_score, recall

def extract_wer(wer_file):
    with open(wer_file, 'r') as r:
        first_line = r.readline()
        wer = float(first_line.split()[1])
        err = int(first_line.split()[3])
        total = int(first_line.split()[5][:-1])
        
        wer_details = {'wer': wer, 'err': err, 'tot': total}


    return wer_details

def transcription_helper_MTL(words):
    # For a given list of words, return list of paraphasias (strings)
    paraphasia_list = []
    for i,w in enumerate(words):
        if '/' in w:
            paraphasia_list.append(w.split('/')[-1].lower())
        elif w == '<eps>':
            paraphasia_list.append('c')


    return paraphasia_list
    
def extract_word_level_paraphasias(wer_file):
    # Extract word-level paraphasias from transcription WER file
    # Words (no tag -> C)

    # AWER
    y_true = []
    y_pred = []
    with open(wer_file, 'r') as r:
        lines = r.readlines()
        switch = 0
        for line in lines:
            line = line.strip()
            if line.startswith("P") and len(line.split()) == 14 and switch == 0:
                utt_id = line.split()[0][:-1]
                switch=1
            elif switch == 1:
                # ground truth
                words = [w.strip() for w in line.split(";")]
                # print(f"gt: {words}")
                paraphasia_list = transcription_helper_MTL(words)
                # print(f"gt_para: {paraphasia_list}")
                y_true.append(paraphasia_list)
                switch = 2


            elif switch == 2:
                switch = 3
            elif switch ==3:
                # pred
                words = [w.strip() for w in line.split(";")]
                # print(f"PRED words: {words}")
                paraphasia_list = transcription_helper_MTL(words)
                # print(f"pred_para: {paraphasia_list}")
                y_pred.append(paraphasia_list)
                switch = 0
                # assert len(pred) == len(gt)
    return y_true, y_pred

def get_metrics(fold_dir):
    '''
    Compute WER metric for a given fold dir
    Compile list of lists y_true and y_pred for paraphasia analysis
    '''
    wer_file = f"{fold_dir}/awer_para.txt"
    wer_details = extract_wer(wer_file)


    # Extract paraphasia sequence from wer.txt
    list_list_ytrue, list_list_ypred = extract_word_level_paraphasias(wer_file)

    result_df = pd.DataFrame({
        'wer-err': [wer_details['err']],
        'wer-tot': [wer_details['tot']],
    })

    return result_df, list_list_ytrue, list_list_ypred
    
def clean_FT_model_save(path):
    # keep only 1 checkpoint, remove optimizer
    save_dir = f"{path}/save"
    abs_directory = os.path.abspath(save_dir)


    files = os.listdir(abs_directory)

    # Filter files that start with 'CKPT'
    ckpt_files = [f for f in files if f.startswith('CKPT')]

    # If no CKPT files, return
    if not ckpt_files:
        print("No CKPT files found.")
        return

    # Sort files lexicographically, this works because the timestamp format is year to second
    ckpt_files.sort(reverse=True)

    # The first file in the list is the latest, assuming the naming convention is consistent
    latest_ckpt = ckpt_files[0]
    print(f"Retaining the latest CKPT file: {latest_ckpt}")


    # Remove all other CKPT files
    for ckpt in ckpt_files[1:]:
        shutil.rmtree(os.path.join(abs_directory, ckpt))
        print(f"Deleted CKPT file: {ckpt}")

    # remove optimizer
    optim_file = f"{abs_directory}/{latest_ckpt}/optimizer.ckpt"
    os.remove(optim_file)



def change_yaml(yaml_src,yaml_target,data_fold_dir,frid_fold,output_neurons,output_dir,base_model,freeze_arch_bool):
    # copy src to tgt
    shutil.copyfile(yaml_src,yaml_target)

    # edit target file
    train_flag = True
    reset_LR = True # if true, start lr with init_LR
    output_dir = f"{output_dir}/Fold-{frid_fold}"
    lr = 5.0e-4 # 1e-3 for frozen arch
    
    
    # copy original file over to new dir
    if not os.path.exists(output_dir):
        print("copying dir")
        shutil.copytree(base_model,output_dir, ignore_dangling_symlinks=True)
        clean_FT_model_save(output_dir)

        
        
    # replace with raw text
    with open(yaml_target) as fin:
        filedata = fin.read()
        filedata = filedata.replace('data_dir_PLACEHOLDER', f"{data_fold_dir}")
        filedata = filedata.replace('train_flag_PLACEHOLDER', f"{train_flag}")
        filedata = filedata.replace('FT_start_PLACEHOLDER', f"{reset_LR}")
        filedata = filedata.replace('epochs_PLACEHOLDER', f"{TOT_EPOCHS}")
        filedata = filedata.replace('frid_fold_PLACEHOLDER', f"{frid_fold}")
        filedata = filedata.replace('output_PLACEHOLDER', f"{output_dir}")
        filedata = filedata.replace('output_neurons_PLACEHOLDER', f"{output_neurons}")
        filedata = filedata.replace('lr_PLACEHOLDER', f"{lr}")
        filedata = filedata.replace('freeze_ARCH_PLACEHOLDER', f"{freeze_arch_bool}")


        with open(yaml_target,'w') as fout:
            fout.write(filedata)

    return output_dir

def utt_f1_sig_check(DUC_DIR,PARA_TYPE,y_true,utt_id2f1pred):
    with open(f'{DUC_DIR}/f1_outs_{PARA_TYPE}.pkl', 'rb') as r:
        duc_results = pickle.load(r)

        duc_pred = duc_results['pred']
        duc_true = duc_results['true']
        duc_ids = duc_results['ids']
        s2s_pred = [utt_id2f1pred[i] for i in duc_results['ids']]

        print(f"duc_pred: {duc_pred}")
        print(f"s2s_pred: {s2s_pred}")
        exit()
        t_statistic, p_value = stats.ttest_rel(duc_pred, y_pred)

if __name__ == "__main__":
    DATA_ROOT = "/home/mkperez/speechbrain/AphasiaBank/data/Fridriksson_para_best_Word"

    TRAIN_FLAG = False
    EVAL_FLAG = True
    OUTPUT_NEURONS=500
    FREEZE_ARCH = False

    if FREEZE_ARCH:
        BASE_MODEL = f"ISresults/MTL_proto/S2S-hubert-Transformer-500"
        EXP_DIR = f"ISresults/MTL_Scripts/S2S-hubert-Transformer-500"
    else:
        BASE_MODEL = f"ISresults/full_FT_MTL_proto/S2S-hubert-Transformer-500"
        EXP_DIR = f"ISresults/full_FT_MTL_Scripts/S2S-hubert-Transformer-500"

    if TRAIN_FLAG:
        yaml_src = "/home/mkperez/speechbrain/AphasiaBank/hparams/Scripts/MTL_base.yml"
        yaml_target = "/home/mkperez/speechbrain/AphasiaBank/hparams/Scripts/MTL_fold.yml"
        start = time.time()
        
        i=1
        count=0
        while i <=12:
            data_fold_dir = f"{DATA_ROOT}/Fold_{i}"

            change_yaml(yaml_src,yaml_target,data_fold_dir,i,OUTPUT_NEURONS,EXP_DIR,BASE_MODEL,FREEZE_ARCH)

            # # launch experiment
            # multi-gpu
            env = os.environ.copy()
            env['CUDA_VISIBLE_DEVICES'] = '0'
            port = find_free_port()  # Get a free port.
            print(f"free port: {port}")
            # cmd = ['torchrun', '--nproc_per_node=1',
            #        f'--master_port={str(port)}', 
            #     'train_MTL.py', f'{yaml_target}',
            #     '--distributed_launch', '--distributed_backend=nccl', '--find_unused_parameters']

            cmd = ['python', '-m', 'torch.distributed.launch',
                   f'--master_port={str(port)}', 
                'train_MTL.py', f'{yaml_target}']
            
            p = subprocess.run(cmd, env=env)

            # p = subprocess.run(cmd)
            count+=1
            print(f"p.returncode: {p.returncode} | retry: {count}")

            if p.returncode == 0:
                i+=1


        end = time.time()
        elapsed = end-start
        print(f"Total Train runtime: {datetime.timedelta(seconds=elapsed)}")

    ##  Stat computation
    if EVAL_FLAG:
        results_dir = f"{EXP_DIR}/results"
        os.makedirs(results_dir, exist_ok=True)

        df_list = []
        y_true = [] # aggregate list of y_true(list)
        y_pred = []
        for i in range(1,13):
            Fold_dir = f"{EXP_DIR}/Fold-{i}"
            result_df, list_list_ytrue, list_list_ypred = get_metrics(Fold_dir)

            # Combine over all folds
            y_true.extend(list_list_ytrue)
            y_pred.extend(list_list_ypred)
            df_list.append(result_df)
 
        df = pd.concat(df_list)



        # Recall-f1 localization
        zero_f1, zero_recall = compute_time_tolerant_scores(y_true, y_pred, n=0)
        one_f1, one_recall = compute_time_tolerant_scores(y_true, y_pred, n=1)
        two_f1, two_recall = compute_time_tolerant_scores(y_true, y_pred, n=2)

        # TD
        TD_per_utt = compute_temporal_distance(y_true, y_pred)


        with open(f"{results_dir}/Frid_metrics_multi.txt", 'w') as w:
            for k in ['wer']:
                wer = df[f'{k}-err'].sum()/df[f'{k}-tot'].sum()
                print(f"{k}: {wer}")
                w.write(f"{k}: {wer}\n")
            

            print("Time Tolerant Recall:")
            print(f"0: {zero_recall}")
            print(f"1: {one_recall}")
            print(f"2: {two_recall}")

            print("Time Tolerant F1")
            print(f"0: {zero_f1}")
            print(f"1: {one_f1}")
            print(f"2: {two_f1}")

            print(f"TD per utt: {TD_per_utt}")  

            w.write(f"Time Tolerant Recall:\n")
            w.write(f"0: {zero_recall}\n")
            w.write(f"1: {one_recall}\n")
            w.write(f"2: {two_recall}\n\n")

            w.write(f"Time Tolerant F1:\n")
            w.write(f"0: {zero_f1}\n")
            w.write(f"1: {one_f1}\n")
            w.write(f"2: {two_f1}\n\n")

            w.write(f"TD per utt: {TD_per_utt}\n\n")


        

        

        


