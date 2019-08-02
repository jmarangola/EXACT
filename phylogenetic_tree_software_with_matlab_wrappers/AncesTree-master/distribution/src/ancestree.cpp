/*
 *  ancestree.cpp
 *
 *   Created on: 27-mar-2015
 *       Author: M. El-Kebir
 */

#include <lemon/arg_parser.h>
#include <fstream>

#include "config.h"
#include "utils.h"
#include "readcountmatrix.h"
#include "ancestrymatrix.h"
#include "probancestrygraph.h"
#include "intmaxilpsolver.h"
#include "solutiongraph.h"

using namespace vaff;

int main(int argc, char** argv)
{
  lemon::ArgParser ap(argc, argv);
  
  double alpha = 0.3;
  double beta = 0.8;
  double gamma = 0.01;
  
  int timeLimit = -1;
  
  std::string solOutput;
  std::string dotOutput;
  
  ap.boolOption("-version", "Show version number")
    .synonym("v", "-version")
    .refOption("-alpha", "Clustering parameter (default: 0.3)", alpha)
    .synonym("a", "-alpha")
    .refOption("-beta", "Ancestry parameter (default: 0.8)", beta)
    .synonym("b", "-beta")
    .refOption("-gamma", "Width of confidence interval (default: 0.01)", gamma)
    .synonym("g", "-gamma")
    .refOption("-sol", "Solution output filename (default: STDOUT)", solOutput)
    .synonym("s", "-sol")
    .refOption("-dot", "Tree DOT output filename (default: /dev/null)", dotOutput)
    .synonym("d", "-dot")
    .refOption("-time", "Time limit (default: -1, disabled)", timeLimit)
    .synonym("t", "-time")
    .other("read_count_file", "Read counts");
  ap.parse();
  
  if (ap.given("-version"))
  {
    std::cout << "Version number: " << ANCESTREE_VERSION << std::endl;
    return 0;
  }
  
  if (ap.files().size() == 0)
  {
    std::cerr << "Error: missing read_count_file" << std::endl;
    return 1;
  }
  
  if (!(0 <= alpha && alpha <= 0.5))
  {
    std::cerr << "Error: value of alpha should be in [0,0.5]" << std::endl;
    return 1;
  }
  
  if (!(0.5 <= beta && beta <= 1))
  {
    std::cerr << "Error: value of beta should be in [0.5,1]" << std::endl;
    return 1;
  }
  
  if (!(0 <= gamma && gamma <= 1))
  {
    std::cerr << "Error: value of gamma should be in [0,1]" << std::endl;
    return 1;
  }
  
  ReadCountMatrix R;
  std::ifstream in(ap.files()[0].c_str());
  if (!in.good())
  {
    std::cerr << "Error: failed to open '" << ap.files()[0] << "' for reading" << std::endl;
    return 1;
  }
  std::cerr << "Parsing read count input..." << std::endl;
  in >> R;
  in.close();
  std::cerr << "#samples: " << R.getNrCols() << std::endl
            << "#mutations: " << R.getNrRows() << std::endl << std::endl;
  
  // order hard-coded to 0
  std::cerr << "Computing ancestry matrix..." << std::endl;
  AncestryMatrix A(R, 0);
  std::cerr << std::endl;
  
  std::cerr << "Computing ancestry graph..." << std::endl;
  ProbAncestryGraph G(A, R, alpha, gamma);
  std::cerr << "|V| = " << lemon::countNodes(G.getG()) << std::endl;
  std::cerr << "|A| = " << lemon::countArcs(G.getG()) << std::endl << std::endl;
  
  std::cerr << "Clustering ancestry graph..." << std::endl;
  StlIntMatrix toOrginalColumns;
  G.removeCycles(A, alpha, toOrginalColumns);
  RealMatrix F;
  R.computePointEstimates(F);
  std::cerr << "\nThe point estimates F: \n";
  std::cerr << F;
  std::cerr << "\nThe point estimates R values: \n";
  std::cerr << R;

  ReadCountMatrix newR = R.collapse(toOrginalColumns);

  std::cerr << "\nThe new R values, right after collapse: \n";
  std::cerr << newR;

  RealIntervalMatrix CI(newR.getNrCols(), newR.getNrRows());
  newR.computeConfidenceIntervals(CI, gamma);
  ProbAncestryGraph H;
  G.contract(A, toOrginalColumns, beta, H);

  //Printing the potential cluster information
  std::cerr << "\nThe new CI matrix: \n";
  std::cerr << CI;
  std::cerr << "\nThe new R values: \n";
  std::cerr << newR;
  
  std::cerr << "|V| = " << lemon::countNodes(H.getG()) << std::endl;
  std::cerr << "|A| = " << lemon::countArcs(H.getG()) << std::endl << std::endl;
  
  std::cerr << "The F values right before ILP: \n";
  std::cerr << F;
  std::cerr << "Constructing ILP..." << std::endl;
  IntMaxIlpSolver solver(H,
                         CI,
                         F,
                         toOrginalColumns,
                         timeLimit);
  
  std::cerr << "Solving ILP..." << std::endl;
  MaxSolution solution(F);
  std::cerr << "F after solving ILP...\n" << F << std::endl;
  solver.solve(solution);
  
  if (solOutput == "")
  {
    std::cout << solution;
  }
  else
  {
    std::ofstream out(solOutput.c_str());
    out << solution;
    out.close();
  }
  
  if (dotOutput != "")
  {
    solution.remapLabels(5);
    SolutionGraph graph(solution.solution(0), 0.05, beta);
    
    std::ofstream out(dotOutput.c_str());
    graph.writeDOT(out);
    out.close();
  }
  
  return 0;
}
