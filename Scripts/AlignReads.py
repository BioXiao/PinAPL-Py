#!/usr/bin/python
# -*- coding: utf-8 -*-
"""
Created on Mon May 16 19:11:28 2016

@author: philipp
"""

# Perform alignment, count & normalize reads
# =======================================================================
# Imports
from __future__ import division # floating point division by default
import pandas
from Bowtie2 import RunBowtie2
import yaml
import os
import glob
import time
import sys
from collections import Counter
from joblib import Parallel, delayed
import multiprocessing
from mpl_toolkits.mplot3d import axes3d
import matplotlib
matplotlib.use('Agg') 
import matplotlib.pyplot as plt
import numpy
import pysam
from matplotlib.ticker import FuncFormatter

def millions(x, pos):
    return '%1.1fM' % (x*1e-6)

def millions2(x, pos):
    return '%1.2fM' % (x*1e-6)    

def CountReadsPerGene(g):
    global GeneList
    global geneIDs
    global ReadsPerGuide
    gene = GeneList[g]        
    geneIndex = [i for i,x in enumerate(geneIDs) if x==gene]
    sgCounts = [ReadsPerGuide[i] for i in geneIndex]
    g_counts = sum(sgCounts)
    return g_counts  

def CountReadsPerGeneX(g):
    gene = GeneList[g]        
    I = geneIDs.index(gene)
    j = I
    g_counts = 0
    terminate = False
    while geneIDs[j] == gene and terminate == False:
        g_counts = g_counts + ReadsPerGuide[j]
        if j <= L-2:
            j+=1  
        else:
            terminate = True
    return g_counts  


def MapAndCount(sample):    
    # ------------------------------------------------
    # Print header
    # ------------------------------------------------
    print('++++++++++++++++++++++++++++++++++++++++++++++++')  
    start_total = time.time()   

    # ------------------------------------------------
    # Get parameters
    # ------------------------------------------------
    configFile = open('configuration.yaml','r')
    config = yaml.load(configFile)
    configFile.close()
    ScriptsDir = config['ScriptsDir']
    WorkingDir = config['WorkingDir']
    TempDataDir = config['TempDataDir']
    AnalysisDir = config['AnalysisDir']
    CutAdaptDir = config['CutAdaptDir']
    bw2Dir = config['bw2Dir']
    IndexDir = config['IndexDir']
    LibDir = config['LibDir']
    AlnStemDir = config['AlignDir']
    AlnDir = AlnStemDir+sample+'/'
    OutputDir = config['AlnQCDir']+sample   
    minN = config['Cutoff']
    LibFilename = config['LibFilename']
    LibFormat = LibFilename[-3:]
    if LibFormat == 'tsv':
        libsep = '\t'
    elif LibFormat == 'csv':
        libsep = ','
    Theta = config['Theta']
    AS_min = config['AS_min']
    L_bw = config['L_bw']
    N_bw = config['N_bw']
    i_bw = config['i_bw']
    N0 = 1000000
    res = config['dpi']
    svg = config['svg']
    AlnOutput = config['AlnOutput']
    keepCutReads = config['keepCutReads']
    AlnFileSuffix = '_bw2Aln.txt'
    GuideCount_Suffix = '_GuideCounts.txt'
    GeneCount_Suffix = '_GeneCounts.txt'
    cutadaptLog = sample+'_cutadapt_log.txt'
    logfilename = sample+'_AlignmentResults.txt'
    
    # ------------------------------------------------
    # Read library
    # ------------------------------------------------  
    os.chdir(LibDir)
    LibCols = ['gene','ID','seq']
    LibFile = pandas.read_table(LibFilename, sep = libsep, skiprows = 1, names = LibCols)
    LibFile = LibFile.sort_values(['gene','ID'])    
    sgIDs = list(LibFile['ID'])
    global L
    L = len(sgIDs)
    global geneIDs
    geneIDs = list(LibFile['gene'])
    G = len(set(geneIDs))
    
    # ------------------------------------------------
    # Get sample read file
    # ------------------------------------------------      
    os.chdir(WorkingDir)
    DataSheet = pandas.read_excel('DataSheet.xlsx')
    FileNames = list(DataSheet['FILENAME'].values)
    n = len(FileNames)
    Samples = list(DataSheet['SAMPLE NAME'].values)
    ReadsFilename = [FileNames[j] for j in range(n) if Samples[j] == sample][0] 
    ReadsFilename0 = 'Trim_'+ReadsFilename    

    # ----------------------------------------------
    # Run alignment
    # ----------------------------------------------                  
    start = time.time()  
    print('Aligning reads to library ...')        
    RunBowtie2(ReadsFilename0,TempDataDir,AlnDir,bw2Dir,IndexDir,L_bw,N_bw,i_bw)
    print('Alignment completed.')
    end = time.time()
    # Time stamp
    aln_time = end-start
    if aln_time < 60: 
        time_elapsed = aln_time
        print('Time elapsed (Alignment) [secs]: ' + '%.3f' % time_elapsed)
    elif aln_time < 3600:
        time_elapsed = aln_time/60
        print('Time elapsed (Alignment) [mins]: ' + '%.3f' % time_elapsed)
    else:
        time_elapsed = aln_time/3600
        print('Time elapsed (Alignment) [hours]: ' + '%.3f' % time_elapsed)


    # ------------------------------------------
    # Extract and analyze alignments
    # ------------------------------------------ 
    start = time.time()
    print('Analyzing alignment ...') 
    print('Applying matching threshold ...')
    print('Applying ambiguity threshold ...')    
    # CLASSIFY ALIGNMENTS 
    os.chdir(AlnDir)
    bw2outputFilename = ReadsFilename0 + '_bw2output.sam'
    bw2sam = pysam.AlignmentFile(bw2outputFilename,'rb')
    NFail = 0; NUnique = 0; NTol = 0; NAmb = 0
    mapQ = list()
    primScore = list()
    secScore = list()
    AlnStatus = list()
    sgRNA_Hitlist = list()
    for read in bw2sam.fetch():        
        mapQ.append(read.mapping_quality)
        # read with primary and seconday alignment
        if read.has_tag('AS'):
            AS = read.get_tag('AS')            
            if AS >= AS_min:                
                if read.has_tag('XS'):
                    XS = read.get_tag('XS')       
                    primScore.append(AS)
                    secScore.append(XS)            
                    if XS <= AS - Theta:
                        NTol += 1
                        AlnStatus.append('Tolerate')
                        sgRNA_Hitlist.append(read.reference_name)
                    else:
                        NAmb += 1  
                        AlnStatus.append('Ambiguous')
                # read with only primary alignment
                else:
                    primScore.append(AS)
                    secScore.append(0)
                    NUnique += 1
                    AlnStatus.append('Unique')
                    sgRNA_Hitlist.append(read.reference_name)                
            else:
                # read with insufficient primary score 
                primScore.append(AS)                
                if read.has_tag('XS'):
                    XS = read.get_tag('XS')
                    secScore.append(XS)
                else:
                    secScore.append(0)          
                NFail += 1
                AlnStatus.append('Fail')
        # read with failed alignment
        else:
            primScore.append(0)
            secScore.append(0)
            NFail += 1
            AlnStatus.append('Fail')
    bw2sam.close();          
    NReads = NTol + NAmb + NUnique + NFail
    FracUnique = round(NUnique/NReads*1000)/10    
    FracTol = round(NTol/NReads*1000)/10
    FracAmb = round(NAmb/NReads*1000)/10
    FracFail = round(NFail/NReads*1000)/10         
    print('*** Successfully mapped reads: '\
        +str(NUnique+NTol)+' ('+str(FracUnique+FracTol)+'%) ***')
    
    
    # ------------------------------------------
    # Text output and plots
    # ------------------------------------------ 
    print('Writing alignment logfile ...')  
    if aln_time < 60:
        time_elapsed = aln_time
        time_unit = ' [secs]'
    elif aln_time < 3600:
        time_elapsed = aln_time/60
        time_unit = ' [mins]'
    else:
        aln_time = aln_time/3600
        time_unit = ' [hours]'  
    if not os.path.exists(OutputDir):
        os.makedirs(OutputDir)        
    os.chdir(OutputDir)    
    LogFile = open(logfilename,'w')         
    LogFile.write(sample+' Alignment Results\n')
    LogFile.write('**************************************\n')
    LogFile.write('\n')
    LogFile.write('Total Number of Reads: \t'+str(NReads)+'\n')    
    LogFile.write('\n')    
    LogFile.write('Number of Reads with unique Alignments: \t'+str(NUnique)+' ('+str(FracUnique)+'%)\n')
    LogFile.write('Number of Reads above Ambiguity Tolerance: \t'+str(NTol)+' ('+str(FracTol)+'%)\n')
    LogFile.write('---------------------------------------------------------------\n')
    LogFile.write('Total Number of Reads matched: \t\t\t'+str(NUnique+NTol)+' ('+str(FracUnique+FracTol)+'%)\n')
    LogFile.write('\n\n')    
    LogFile.write('Number of Reads below Ambiguity Tolerance: \t'+str(NAmb)+' ('+str(FracAmb)+'%)\n')
    LogFile.write('Number of Reads with failed Alignment: \t\t'+str(NFail)+' ('+str(FracFail)+'%)\n')
    LogFile.write('---------------------------------------------------------------\n')
    LogFile.write('Total Number of Reads discarded: \t\t'+str(NFail+NAmb)+' ('+str(FracFail+FracAmb)+'%)\n')    
    LogFile.write('\n\n\n')    
    LogFile.write('---- Alignment completed in %.2f' % time_elapsed + time_unit+' ----')
    LogFile.write('\n\n\n')        
    LogFile.write('Parameter settings\n')
    LogFile.write('L_bw (Seed Length): '+str(L_bw)+'\n')    
    LogFile.write('N_bw (Seed Mismatch): '+str(N_bw)+'\n')    
    LogFile.write('i_bw (Interval Function): '+str(i_bw)+'\n')        
    LogFile.write('Theta (Ambiguity Threshold): '+str(Theta)+'\n')    
    LogFile.write('AS_min (Matching Threshold): '+str(AS_min)+'\n')        
    LogFile.close()              
    # DRAW PLOTS
    # MAPPING QUALITY HISTOGRAM
    os.chdir(OutputDir)
    print('Plotting mapping quality ...')
    maxQuality = max(mapQ)
    fig, ax = plt.subplots(figsize=(5,3.5))
    plt.hist(mapQ, bins = range(maxQuality+1), width = 1, align = 'left')
    plt.xlim([-1,maxQuality+1])
    plt.title('Read Alignment Rates', fontsize=14)
    plt.xlabel('Mapping Quality', fontsize=14)
    plt.ylabel('Number of Reads', fontsize=14)
    plt.tick_params(labelsize=14)
    formatter = FuncFormatter(millions2)
    ax.yaxis.set_major_formatter(formatter) 
    plt.tight_layout()
    plt.savefig(sample+'_MappingQuality.png',dpi=res)  
    if svg:
        plt.savefig(sample+'_MappingQuality.svg')  
    # ALIGNMENT SCORE BARPLOT
    print('Plotting alignment scores ...')
    primScoreKeep = [primScore[k] for k in range(NReads) if AlnStatus[k] in ['Unique','Tolerate']]
    secScoreKeep = [secScore[k] for k in range(NReads) if AlnStatus[k] in ['Unique','Tolerate']]    
    primScoreToss = [primScore[k] for k in range(NReads) if AlnStatus[k] in ['Fail','Ambiguous']]
    secScoreToss = [secScore[k] for k in range(NReads) if AlnStatus[k] in ['Fail','Ambiguous']]
    # Plot bars (matched reads)
    xedges = range(42)
    yedges = range(42)
    H, xedges, yedges = numpy.histogram2d(secScoreKeep, primScoreKeep, bins=(xedges, yedges))
    Y, X = numpy.nonzero(H)
    Z = H[Y,X]
    Z_off = numpy.zeros(len(Y))
    dX = numpy.ones(len(X))
    dY = numpy.ones(len(Y))
    # Plot bars (discarded reads)
    h, xedges, yedges = numpy.histogram2d(secScoreToss, primScoreToss, bins=(xedges, yedges))
    y, x = numpy.nonzero(h)
    z = h[y,x]
    z_off = numpy.zeros(len(y))
    dx = numpy.ones(len(x))
    dy = numpy.ones(len(y))
    # Show plot    
    fig = plt.figure(figsize=(6,5))
    ax = fig.gca(projection='3d')
    ax.bar3d(X,Y,Z_off,dX,dY,Z, color=(97/255, 252/255, 80/255))  # bar3d has a bug with hex code
    green_proxy = plt.Rectangle((0, 0), 1, 1, fc=(97/255, 252/255, 80/255))
    ax.bar3d(x,y,z_off,dx,dy,z,color=(255/255, 51/255, 51/255))
    red_proxy = plt.Rectangle((0, 0), 1, 1, fc=(255/255, 51/255, 51/255))
    ax.legend([green_proxy,red_proxy],['Reads Accepted','Reads Discarded'],loc='upper left',prop={'size':10})
    ax.set_title('Alignment Analysis',fontsize=14)
    ax.set_xlabel('Prim. Alignment Score', fontsize=12)
    ax.set_ylabel('Sec. Alignment Score', fontsize=12)
    formatter = FuncFormatter(millions)
    ax.zaxis.set_major_formatter(formatter)    
    ax.set_zlabel('Number of Reads',fontsize=12)
    ax.set_xticks([0,10,20,30,40]); ax.set_yticks([0,10,20,30,40]);
    plt.tight_layout()    
    plt.savefig(sample+'_AlignmentScores.png',dpi=res)   
    if svg:
        plt.savefig(sample+'_AlignmentScores.svg',dpi=res)
    print('Alignment analysis completed.')  
    end = time.time()
    # Time stamp
    sec_elapsed = end-start
    if sec_elapsed < 60: 
        time_elapsed = sec_elapsed
        print('Time elapsed (Alignment analysis) [secs]: ' + '%.3f' % time_elapsed)
    elif sec_elapsed < 3600:
        time_elapsed = sec_elapsed/60
        print('Time elapsed (Alignment analysis) [mins]: ' + '%.3f' % time_elapsed)
    else:
        time_elapsed = sec_elapsed/3600
        print('Time elapsed (Alignment analysis) [hours]: ' + '%.3f' % time_elapsed)
        
    
    # --------------------------------------
    # Get read counts
    # --------------------------------------
    start = time.time()    
    print('Read counting in progress ...')
    # Read counts per sgRNA
    print('Counting reads per sgRNA ...')
    ReadCounts = Counter()
    for sgRNA in sgRNA_Hitlist:
        ReadCounts[sgRNA] += 1
    global ReadsPerGuide
    ReadsPerGuide = list()
    for sgRNA in sgIDs:
        ReadsPerGuide.append(ReadCounts[sgRNA])      
    # Apply read count cut-off
    ReadSel = [ReadsPerGuide[k] >= NReads/N0*minN for k in range(L)]
    ReadsPerGuide = [ReadSel[k]*ReadsPerGuide[k] for k in range(L)]
    # Write read counts   
    os.chdir(OutputDir)         
    GuideCountsFilename = sample + GuideCount_Suffix
    GuideCounts = open(GuideCountsFilename,'w')
    for k in range(L):
        GuideCounts.write(str(sgIDs[k]) + '\t'+ str(geneIDs[k]) + '\t' + str(ReadsPerGuide[k]) + '\n')
    GuideCounts.close()
    # Read counts per gene in library       
    print('Counting reads per gene ...')   
    global GeneList
    GeneList = list(set(geneIDs))   
    G = len(GeneList)  
    num_cores = multiprocessing.cpu_count()
    ReadsPerGene = Parallel(n_jobs=num_cores)(delayed(CountReadsPerGeneX)(g) for g in range(G))  
    GeneCountsFilename = sample + GeneCount_Suffix
    GeneCounts = open(GeneCountsFilename,'w')
    for g in range(G):
        GeneCounts.write(str(GeneList[g]) + '\t' + str(ReadsPerGene[g]) + '\n')
    GeneCounts.close()        
    end = time.time()
    print('Read counting completed.')
    # No-mapping warning
    if sum(ReadsPerGuide) == 0:
        print('### ERROR: Zero read counts! Check library and alignment ###')    
    # Time stamp
    sec_elapsed = end-start
    if sec_elapsed < 60:
        time_elapsed = sec_elapsed
        print('Time elapsed (Read Counting) [secs]: ' + '%.3f' % time_elapsed)
    elif sec_elapsed < 3600:
        time_elapsed = sec_elapsed/60
        print('Time elapsed (Read Counting) [mins]: ' + '%.3f' % time_elapsed)
    else:
        time_elapsed = sec_elapsed/3600
        print('Time elapsed (Read Counting) [hours]: ' + '%.3f' % time_elapsed)


    # --------------------------------------
    # Cleaning up...
    # --------------------------------------
    start = time.time()  
    # clipped reads file    
    if not keepCutReads:        
        os.chdir(TempDataDir)
        os.system('rm '+ReadsFilename0)
    # alignment output        
    if AlnOutput == 'Compress':
        print('Compressing raw alignment output...')
        os.chdir(AlnDir)
        # converting SAM to BAM
        SAM_output = glob.glob('*bw2output.sam')[0]
        BAM_output = SAM_output[:-3] + 'bam'
        os.system('samtools view -buSH '+SAM_output+' > '+BAM_output)
        os.system('rm '+SAM_output) 
    elif AlnOutput == 'Delete':
        print('Removing raw alignment output...')
        os.chdir(AlnDir)
        os.system('rm *')
    elif AlnOutput == 'Keep':
        print('Keeping raw alignment output ...')
    end = time.time()
    # Time stamp
    sec_elapsed = end-start
    if sec_elapsed < 60: 
        time_elapsed = sec_elapsed
        print('Time elapsed (Clean-up) [secs]: ' + '%.3f' % time_elapsed)
    elif sec_elapsed < 3600:
        time_elapsed = sec_elapsed/60
        print('Time elapsed (Clean-up) [mins]: ' + '%.3f' % time_elapsed)
    else:
        time_elapsed = sec_elapsed/3600
        print('Time elapsed (Clean-up) [hours]: ' + '%.3f' % time_elapsed)     

    # --------------------------------------
    # Final time stamp
    # --------------------------------------        
    os.chdir(ScriptsDir)    
    end_total = time.time()
    # Final time stamp
    print('------------------------------------------------')
    print('Script completed.')    
    sec_elapsed = end_total - start_total
    if sec_elapsed < 60:
        time_elapsed = sec_elapsed
        print('Time elapsed (Total) [secs]: ' + '%.3f' % time_elapsed +'\n')
    elif sec_elapsed < 3600:
        time_elapsed = sec_elapsed/60
        print('Time elapsed (Total) [mins]: ' + '%.3f' % time_elapsed +'\n')
    else:
        time_elapsed = sec_elapsed/3600
        print('Time elapsed (Total) [hours]: ' + '%.3f' % time_elapsed +'\n')            
      
if __name__ == "__main__":
    input1 = sys.argv[1]
    MapAndCount(input1)
