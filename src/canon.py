import os
import gc
from collections import Counter
from tools import say
from numpy import array
from numpy.random import randn
from scipy.sparse import csc_matrix 
from scipy.linalg import qr
from scipy.linalg import svd
from numpy.linalg import norm
from time import strftime
import datetime

class canon(object):


    def __init__(self):
        self.wantB = False


    def set_views(self, views):
        assert(os.path.isfile(views))        
        self.views = views

    
    def set_wantB(self, wantB):
        self.wantB = wantB

    
    def set_params(self, cca_dim, kappa, extra_dim, power_num):
        self.cca_dim = cca_dim
        self.kappa = kappa
        self.extra_dim = extra_dim
        self.power_num = power_num

                
    def start_logging(self):
        self.dirname = 'output/{}.cca_dim{}.kappa{}.extra_dim{}.power_num{}.out'.\
                        format(os.path.basename(self.views), self.cca_dim, self.kappa, self.extra_dim, self.power_num) 
        if not os.path.exists(self.dirname):
            os.makedirs(self.dirname)                
        self.logf = open(self.dirname+'/log', 'wb')
        self.start_time = datetime.datetime.now().replace(microsecond=0)
        self.rec(strftime('\nStart time: %Y-%m-%d %H:%M:%S'))
        self.rec('________________________________________')


    def end_logging(self):
        self.rec('________________________________________')
        self.rec(strftime('\nEnd time: %Y-%m-%d %H:%M:%S'))
        self.end_time = datetime.datetime.now().replace(microsecond=0)
        self.rec('\nTotal time: ' + str(self.end_time - self.start_time))
        self.logf.close()
        

    def rec(self, string, newline=True):
        if newline:
            print >> self.logf, string
            self.logf.flush()
        else:
            print string,
            self.logf.flush()
        say(string)        

    
    def get_stats(self):        
        self.v1_i = {}
        self.v2_i = {}
        self.v1_w = {}
        self.v2_w = {} # will not build this if not wantB
    
        self.countsXY = Counter()
        self.countsX = Counter()
        self.countsY = Counter()
    
        self.num_samples = 0
        i1 = 0 # distinct number per feature in view 1 
        i2 = 0 # distinct number per feature in view 2
        
        self.rec('\nGetting statistics from: %s' % self.views)
        
        with open(self.views) as f:
            for line in f:
                toks = line.split()
                count = int(toks[0])
                self.num_samples += count
                
                curtain = toks.index('|:|')
                
                # view 1 features
                for i in range(1, curtain):
                    if not toks[i] in self.v1_i:
                        self.v1_i[toks[i]] = i1
                        self.v1_w[i1] = toks[i]
                        i1 += 1
                    view1 = self.v1_i[toks[i]]
                    self.countsX[view1] += count
                
                # view 2 features
                for j in range(curtain+1, len(toks)):
                    if not toks[j] in self.v2_i:
                        self.v2_i[toks[j]] = i2
                        self.v2_w[i2] = toks[j]
                        i2 += 1
                    view2 = self.v2_i[toks[j]]
                    self.countsY[view2] += count
                    for i in range(1, curtain):
                        view1 = self.v1_i[toks[i]]
                        self.countsXY[view1, view2] += count

        self.rec('\nConverting the statistics to matrices')
        self.countsXY = csc_matrix((self.countsXY.values(), zip(*self.countsXY.keys())), shape=(len(self.countsX), len(self.countsY)))
        self.countsX = array([self.countsX[j] for j in range(len(self.countsX))])
        self.countsY = array([self.countsY[j] for j in range(len(self.countsY))])            

    
    def approx_cca(self):        
        self.rec('\nPerforming approximate CCA:')
        self.rec('\n1. Pseudo-whitening')    
        invsqrt_covX = self.compute_invsqrt_cov(self.countsX + self.kappa, self.num_samples + len(self.countsX) * self.kappa)
        invsqrt_covY = self.compute_invsqrt_cov(self.countsY + self.kappa, self.num_samples + len(self.countsY) * self.kappa)

        XY = (1./self.num_samples) * invsqrt_covX * self.countsXY * invsqrt_covY # still sparse
        X  = csc_matrix((1./self.num_samples) * invsqrt_covX * self.countsX).T
        Y  = csc_matrix((1./self.num_samples) * invsqrt_covY * self.countsY).T
        
        del self.countsXY; gc.collect() # try to free some memory

        self.rec('\n\tO := XY - X * Y\' is the pseudo-whitened {} x {} correlation matrix where'.format(XY.shape[0], XY.shape[1]))
        self.rec('\n\t- XY has dimensions {} x {} (sparse: has {} nonzeros)'.format(XY.shape[0], XY.shape[1], XY.nnz))
        self.rec('\t- X has length {}'.format(X.shape[0]))
        self.rec('\t- Y has length {}'.format(Y.shape[0]))

        self.rec('\n2. Approximate SVD on O')
        U, self.corr, V = self.approx_svd(XY, X, Y)
    
        # de-whitening
        self.rec('\n3. De-whitening')
        self.A = invsqrt_covX * U;
        self.B = invsqrt_covY * V;


    def approx_svd(self, XY, X, Y):
        d1, d2 = XY.shape
        
        # find orth Q such that the range of XY - X*Y' is close to the range of (Q*Q') * (XY - X*Y')
        self.rec('\n\tAssigning random T (dimensions: {} x {})'.format(d2, self.cca_dim + self.extra_dim))
        T = randn(d2, self.cca_dim + self.extra_dim)

        self.rec('\n\tComputing Z = O * T (dimensions: {} x {})'.format(d1, T.shape[1]))
        Z = XY * T - X * (Y.T * T)
        del T; gc.collect()
        
        self.rec('\n\tKeep computing Z = (O * O\') * Z')
        for i in range(self.power_num): # power iteration
            self.rec('\t\tPower iteration {} / {}'.format(i+1, self.power_num)) 
            t1 = XY * (XY.T * Z)
            t2 = XY * (Y * (X.T * Z))
            t3 = X * (Y.T * (XY.T * Z))
            t4 = X * (Y.T * (Y * (X.T * Z)))
            Z = t1 - t2 - t3 + t4
        
        self.rec('\n\tObtain an orthonormal basis Q of range(Z) by computing QR(Z) = Q * R')
        Q, _ = qr(Z, mode='economic')
        del t1; del t2; del t3; del t4; del Z; gc.collect()
    
        # obtain a smaller matrix and do a thin svd
        self.rec('\n\tPerform SVD on B = Q\' * O which is now a {} x {} matrix (vs. original {} x {})'.format(Q.shape[1], d2, d1, d2))
        B = Q.T * XY - (Q.T * X) * Y.T
        U_low, corr, VT = svd(B, full_matrices=False)
        
        self.rec('\n\tCollecting the top {} SVD components'.format(self.cca_dim))
        corr = corr[:self.cca_dim]
        U = csc_matrix(Q) * U_low[:, :self.cca_dim] # bring U back to the original dimension
        V= VT.T[:, :self.cca_dim]
        
        return U, corr, V

    
    def compute_invsqrt_cov(self, counts, num_samples):
        mean = counts / float(num_samples)
        var = mean - pow(mean, 2)    
        diags = [i for i in range(len(counts))]
        invsqrt_cov = csc_matrix((pow(var, -.5), (diags, diags)), shape=(len(counts), len(counts)))     
        return invsqrt_cov


    def write_result(self):
        self.write_corr()
        self.write_A()
        if self.wantB:
            self.write_B()


    def write_corr(self):
        say('\nNormalizing correlation coefficients and storing them at: %s' % self.dirname+'/corr')
        self.corr = self.corr / max(self.corr)
        with open(self.dirname+'/corr', 'wb') as f:
            for val in self.corr:
                print >> f, val 

        
    def write_A(self):
        self.rec('\nNormalzing rows of A and storing them at: %s' % self.dirname+'/A')
        for i in range(self.A.shape[0]):
            self.A[i,:] /= norm(self.A[i,:])
        
        with open(self.dirname+'/A', 'wb') as f:
            sorted_indices = self.countsX.argsort()[::-1]        
            for i in sorted_indices:
                print >> f, self.countsX[i], self.v1_w[i] # don't write <*> 
                for j in range(len(self.A[i,:])):
                    print >> f, self.A[i,j], 
                print >> f


    def write_B(self):
        self.rec('\nNormalzing rows of B and storing them at: %s' % self.dirname+'/B')
        for i in range(self.B.shape[0]):
            self.B[i,:] /= norm(self.B[i,:])
        
        with open(self.dirname+'/B', 'wb') as f:
            sorted_indices = self.countsY.argsort()[::-1]        
            for i in sorted_indices:
                print >> f, self.countsY[i], self.v2_w[i] # don't write <*>
                for j in range(len(self.B[i,:])):
                    print >> f, self.B[i,j], 
                print >> f

